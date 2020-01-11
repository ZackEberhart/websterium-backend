import asyncio
from sanic import Sanic
from sanic.response import file
from sanic.response import json, text
import json as js
import sys
import random
import pyimgur
import os

application = Sanic("mysterium-backend")

class Ghost:
    hand = None
    psychics_clued = None

    def __init__(self):
        self.hand = []
        self.psychics_clued = []

    def summarizeSelf(self):
        ghost = {}
        ghost["hand"] = self.hand
        ghost["psychics_clued"] = self.psychics_clued
        return ghost

class Psychic:
    pid = None
    stage = None
    hand = None
    current_guess = None
    guesses = None
    story = None

    def __init__(self, pid):
        self.pid = pid
        self.stage = 0
        self.hand = []
        self.current_guess = None
        self.guesses = []
        self.story = []

    def summarizeSelf(self):
        psychic = {}
        psychic["stage"] = self.stage
        psychic["hand"] = self.hand
        psychic["guesses"] = self.guesses
        psychic["current_guess"] = self.current_guess
        psychic["story"] = self.story
        return psychic

class Game:
    dreamsrc, suspectsrc, placesrc, thingsrc  = 4*[list(range(100))]
    suspects=None
    places=None
    things=None
    stories = None

    ghost = None
    psychics = None
    
    def __init__(self, num_psychics, album_lengths):
        self.dreamsrc, self.suspectsrc, self.placesrc, self.thingsrc  = [list(range(album_len)) for album_len in album_lengths]
        self.suspects = random.sample(self.suspectsrc, num_psychics+3)
        self.places = random.sample(self.placesrc, num_psychics+3)
        self.things = random.sample(self.thingsrc, num_psychics+3)
        sopts = random.sample(self.suspects, num_psychics)
        popts = random.sample(self.places, num_psychics)
        topts = random.sample(self.things, num_psychics)
        self.stories = [[sopts[_], popts[_], topts[_]] for _ in range(num_psychics) ]

        self.ghost = Ghost()
        self.psychics = [Psychic(i) for i in range(num_psychics)]

        random.shuffle(self.dreamsrc)
        self.drawDreams()

    def drawDreams(self):
        while len(self.ghost.hand) < 7:
            self.ghost.hand.append(self.dreamsrc.pop())

    def sendDreams(self, pid, dreams):
        if len(dreams) > len(self.ghost.hand): return False
        # dreams = [self.ghost.hand[dream_index] for dream_index in dreams]
        for dream in dreams:
            self.psychics[pid].hand.append(dream)
            self.ghost.hand.remove(dream)
        self.ghost.psychics_clued.append(pid)
        self.drawDreams()
        return True

    def makeGuess(self, pid, guess):
        stage = self.psychics[pid].stage
        if guess in self.psychics[pid].guesses: return False
        self.psychics[pid].current_guess = guess
        return True

    def evaluateGuesses(self):
        for psychic in self.psychics:
            if self.checkGuess(psychic.pid, psychic.current_guess): 
                psychic.guesses = []
                psychic.stage += 1
                psychic.hand = []
                psychic.story.append(psychic.current_guess)
            else:
                psychic.guesses.append(psychic.current_guess)
            psychic.current_guess = None
        self.ghost.psychics_clued = []

    def checkGuess(self, pid, guess):
        return self.stories[pid][self.psychics[pid].stage] == guess

    def currentRound(self, pid):
        return self.psychics[pid].stage

    def advanceRound(self, pid):
        self.psychics[pid].stage += 1
        self.psychics[pid].hand = []

    def doneGuessing(self):
        for psychic in self.psychics:
            if psychic.current_guess==None: return False
        return True
    
    @property
    def state(self):
        state = {}
        state["psychics"] = {}
        for i, psychic in enumerate(self.psychics):
            state["psychics"][i] = psychic.summarizeSelf()
        state["ghost"] = self.ghost.summarizeSelf()
        return state

    @property
    def cards(self):
        return {"suspects": self.suspects, "places": self.places, "things": self.things}
    
    @property
    def cards_list(self):
        return [self.suspects, self.places, self.things]

class Room:

    CLIENT_ID = "69be06b52415788"
    im = pyimgur.Imgur(CLIENT_ID)

    game = None
    clients_list = []
    ghost = None
    psychics = []
    
    async def join(self, client):
        ''' Called when a user connects to the websocket. 
            Creates a unique ID for that user and associates it with the client
            Sends a welcome msg w/ id to that user and broadcasts the updated user_list
        '''
        self.clients_list.append(client)
        data = self.makeData("welcome", "welcome")
        await client.send(data)
        await self.broadcast("user_list", self._userList())

    async def leave(self, client):
        ''' Called when the connection w/ a client breaks
            Removes the client from the clients_list
            Sets the ghost to None or remove client from psychics list
            Broadcasts the updated user_list
        '''
        if client in self.clients_list: self.clients_list.remove(client)
        if self.ghost == client: self.ghost = None
        if client in self.psychics: self.psychics.remove(client)
        await self.broadcast("user_list", self._userList())

    async def handleData(self, client, data):
        ''' Called whenever any user sends a message
            Parses the message and invokes the appropriate callback
        '''
        options = {
            "setRole": self.setRole,
            "startGame": self.startGame,
            "sendDreams": self.sendDreams,
            "makeGuess": self.makeGuess
        }
        d_type = data["type"]
        if d_type in options: await options[d_type](client, data)
        else: raise NameError('Unimplemented data type.') 

    async def setRole(self, client, data):
        ''' Callback when user sends "setRole" message
            Sets self.ghost to client or adds client to self.psychics
            Broadcasts updated user list
        '''
        role = data["message"]
        if role == "ghost":
            if self.ghost and self.ghost != client: self.psychics.append(self.ghost)
            if client in self.psychics: self.psychics.remove(client)
            self.ghost = client
        else:
            if self.ghost == client: self.ghost = None
            if client not in self.psychics: self.psychics.append(client)
        await self.broadcast("user_list", self._userList())

    async def startGame(self, client, data):
        ''' Callback when user sends "startGame" message
            Creates a new Game object w/ the current number of pyschics
            Calls functions to start the first turn
            If no ghost or too few psychics, sends an error msg
        '''

        if(self.ghost and len(self.psychics)>0):
            album_lengths = [len(self.im.get_album(src).images) for src in data["message"]]
            self.game = Game(self.num_psychics, album_lengths)
            await self.sendClientIds()
            await self.broadcast("image_links", await self.getImageLinks(data["message"], self.game.cards))
            await self.broadcast("start", self.game.cards)
            await self.broadcast("stories", self.game.stories)
            await self.broadcast("state", self.game.state)
            await self.ghost.send(self.makeData("ghost_hand", self.game.ghost.hand))
        else:
            data = self.makeData("reject", "Need a ghost and psychic")
            await client.send(data)

    async def getImageLinks(self, album_sources, cards):
        imageLinks = {}
        albums = [self.im.get_album(src) for src in album_sources]
        imageLinks['dreams'] = {i: image.link for i, image in enumerate(albums[0].images)}
        suspectLinks= {i: albums[1].images[i].link for i in cards['suspects']}
        placeLinks = {i: albums[2].images[i].link for i in cards['places']}
        thingLinks= {i: albums[3].images[i].link for i in cards['things']}
        cardLinks = [suspectLinks, placeLinks, thingLinks]
        imageLinks['cards'] = cardLinks
        return imageLinks

    async def sendDreams(self, client, data):
        ''' Callback when ghost user sends a "sendDreams" message
            Updates the game state and broadcasts to all users
            Message includes users awaiting dreams - if empty, ghost can't send more
            If user newly dream'd, they can now make a guess
        '''
        psychic = data["message"]["psychic"]
        dreams = data["message"]["dreams"]
        if self.game.sendDreams(psychic, dreams):
            await self.broadcast("state", self.game.state)
            await self.ghost.send(self.makeData("ghost_hand", self.game.ghost.hand))
        else:
            await client.send(self.makeData("reject", "invalid action"))  

    async def makeGuess(self, client, data):
        ''' Callback when psychic user sends a "makeGuess" message
            Updates the game state and broadcasts to all users
            If all users have made guesses, perform seance and start next turn
        '''
        psychic = self.psychics.index(client)
        guess = data["message"]["guess"]
        if self.game.makeGuess(psychic, guess):
            if self.game.doneGuessing():
                self.game.evaluateGuesses()
            await self.broadcast("state", self.game.state)
        else:
            await client.send(self.makeData("reject", "invalid action")) 

    def makeData(self, d_type, message=""):
        ''' Returns a json message with type and message '''
        return js.dumps({"type": d_type, "message": message})

    async def sendClientIds(self):
        for i, psychic in enumerate(self.psychics):
            try:
                data_out = self.makeData("client_id", i)
                await psychic.send(data_out)
            except:
                await self.leave(psychic)
        try:
            data_out = self.makeData("client_id", "ghost")
            await self.ghost.send(data_out)
        except:
            await self.leave(self.ghost)

    async def broadcast(self, d_type, data, psychics=False):
        ''' Sends a message to all users in the room
            Can choose to exclude the ghost using the "psychics" argument
        '''
        receivers = self.clients_list
        for receiver in receivers:
            try:
                data_out = self.makeData(d_type, data)
                await receiver.send(data_out)
            except:
                await self.leave(receiver)

    
    def _userList(self):
        ''' Returns a list of each user along with their role (psychic, ghost, other) '''
        user_list = {}
        for i, client in enumerate(self.clients_list):
            if client == self.ghost:
                user_list[i] = "Ghost"
            elif client in self.psychics:
                user_list[i] = "Psychic"
            else:
                user_list[i] = ""
        return user_list

    @property
    def full(self):
        return len(self.clients_list)>6

    @property
    def num_psychics(self):
        return len(self.psychics)
    

room = Room()

@application.route('/')
async def index(request):
    return await file('websocket.html')

@application.websocket('/game')
async def feed(request, ws):
    if room.full:
        await ws.send(js.dumps({'type': 'reject', "message": "room's full"}))
        return
    await room.join(ws)
    while True:
        try:
            data = await ws.recv()
            print(data)
        except Exception as e:
            await room.leave(ws)
            break
        else: 
            await room.handleData(ws, js.loads(data))

if __name__ == '__main__':
    application.run(host="0.0.0.0", 
                    port=os.environ.get('PORT') or 8002, 
                    debug=True)


