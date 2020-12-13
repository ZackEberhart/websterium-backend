import asyncio
from sanic import Sanic
from sanic.response import file
from sanic.response import json, text
import json as js
import sys
import random
import pyimgur
import os
import time

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
    ravens = None

    ghost = None
    psychics = None
    current_round = None
    status = None
    
    def __init__(self, num_psychics, album_lengths):
        self.dreamsrc, self.suspectsrc, self.placesrc, self.thingsrc  = [list(range(album_len)) for album_len in album_lengths]
        self.discard = []
        self.suspects = random.sample(self.suspectsrc, num_psychics+3)
        self.places = random.sample(self.placesrc, num_psychics+3)
        self.things = random.sample(self.thingsrc, num_psychics+3)
        sopts = random.sample(self.suspects, num_psychics)
        popts = random.sample(self.places, num_psychics)
        topts = random.sample(self.things, num_psychics)
        self.stories = [[sopts[_], popts[_], topts[_]] for _ in range(num_psychics) ]

        self.ghost = Ghost()
        self.psychics = [Psychic(i) for i in range(num_psychics)]
        self.current_round = 1
        self.status = "ongoing"
        self.ravens = 3

        random.shuffle(self.dreamsrc)
        self.drawDreams()

    def drawDreams(self):
        while len(self.ghost.hand) < 8:
            if(len(self.dreamsrc)==0):
                random.shuffle(self.discard)
                self.dreamsrc = self.discard
                self.discard = []
            card = self.dreamsrc.pop()
            self.ghost.hand.append(card)
            self.discard.append(card)

    def sendDreams(self, pid, dreams):
        if len(dreams) > len(self.ghost.hand): return False
        # dreams = [self.ghost.hand[dream_index] for dream_index in dreams]
        for dream in dreams:
            self.psychics[pid].hand.append(dream)
            self.ghost.hand.remove(dream)
        self.ghost.psychics_clued.append(pid)
        self.drawDreams()
        return True

    def useRaven(self, dreams):
        # dreams = [self.ghost.hand[dream_index] for dream_index in dreams]
        for dream in dreams:
            self.ghost.hand.remove(dream)
        self.ravens -= 1
        self.drawDreams()
        return True

    def makeGuess(self, pid, guess):
        stage = self.psychics[pid].stage
        if guess in self.psychics[pid].guesses: return False
        self.psychics[pid].current_guess = guess
        return True

    def evaluateGuesses(self):
        for pid, psychic in enumerate(self.psychics):
            if self.checkGuess(pid, psychic.current_guess): 
                psychic.guesses = []
                psychic.stage += 1
                psychic.hand = []
                psychic.story.append(psychic.current_guess)
            else:
                psychic.guesses.append(psychic.current_guess)
            psychic.current_guess = None
        self.ghost.psychics_clued = []
        self.current_round+=1
        if(self.isGameWon()):
            self.status = "won"
        elif(self.current_round > 7):
            self.status = "lost"
            for pid, psychic in enumerate(self.psychics):
                psychic.guesses = []
                psychic.stage = 4
                psychic.hand = []
                psychic.story = self.stories[pid]

    def isGameWon(self):
        for psychic in self.psychics:
            if psychic.stage < 3:
                return False
        return True

    def isGameOver(self):
        return self.status != "ongoing"

    def checkGuess(self, pid, guess):
        if self.psychics[pid].stage > 2: return False
        return self.stories[pid][self.psychics[pid].stage] == guess

    def advanceRound(self, pid):
        self.psychics[pid].stage += 1
        self.psychics[pid].hand = []

    def doneGuessing(self):
        for psychic in self.psychics:
            if psychic.stage <=2 and psychic.current_guess==None: return False
        return True

    def removePsychic(self, pid):
        self.psychics.pop(pid)
        self.stories.pop(pid)
        '''If a psychic leaves midgame, adjust the game so that the rest can continue.'''

    
    @property
    def state(self):
        state = {}
        state["psychics"] = {}
        for i, psychic in enumerate(self.psychics):
            state["psychics"][i] = psychic.summarizeSelf()
        state["ghost"] = self.ghost.summarizeSelf()
        state["current_round"] = self.current_round
        state["status"] = self.status
        state["ravens"] = self.ravens
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
    roomname = None
    clients_list = None
    ghost = None
    psychics = None
    usernames = {}

    def __init__(self, roomname):
        self.roomname = roomname
        self.clients_list = []
        self.psychics = []
    
    async def join(self, client, username):
        ''' Called when a user connects to the websocket. 
            Creates a unique ID for that user and associates it with the client
            Sends a welcome msg w/ id to that user and broadcasts the updated user_list
        '''
        if client not in self.clients_list:
            self.clients_list.append(client)
        self.usernames[client] = username
        if self.ghost != client and client not in self.psychics:
            self.psychics.append(client)
        data = self.makeData("join", self.roomname)
        await client.send(data)
        await self.systemMessage(self.usernames[client] + " has joined.")
        await self.broadcast("user_list", self._userList())
        await self.sendClientIds()

    async def leave(self, client):
        ''' Called when the connection w/ a client breaks
            Removes the client from the clients_list
            Sets the ghost to None or remove client from psychics list
            Broadcasts the updated user_list
            If there are no more clients or the ghost leaves, end the game.
        '''
        await self.systemMessage(self.usernames[client] + " has disconnected.")
        if client in self.clients_list: self.clients_list.remove(client)
        if client in self.usernames: self.usernames.pop(client)
        if self.ghost == client: 
            self.ghost = None
        elif client in self.psychics: 
            if self.game:
                self.game.removePsychic(self.psychics.index(client))
            self.psychics.remove(client)
        if self.game:
            if len(self.psychics) == 0 or self.ghost == None:
                self.game = None
                await self.broadcast("game_interrupted")
        await self.broadcast("user_list", self._userList())
        await self.sendClientIds()
        if self.game:
            await self.broadcast("state", self.game.state)
            await self.broadcast("stories", self.game.stories)
        

    async def handleData(self, client, data):
        ''' Called whenever any user sends a message
            Parses the message and invokes the appropriate callback
        '''
        options = {
            "setRole": self.setRole,
            "startGame": self.startGame,
            "sendDreams": self.sendDreams,
            "makeGuess": self.makeGuess,
            "chatMessage": self.handleChatMessage,
            "useRaven": self.useRaven
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
        await self.sendClientIds()

    async def startGame(self, client, data):
        ''' Callback when user sends "startGame" message
            Creates a new Game object w/ the current number of pyschics
            Calls functions to start the first turn
            If no ghost or too few psychics, sends an error msg
        '''
        #Check that there are enough players
        if(len(self.psychics)<len(self.clients_list)-1):
            data = self.makeData("reject", "All users must pick a role")
            await client.send(data)
            return
        if(self.ghost==None or  len(self.psychics)==0):
            data = self.makeData("reject", "Need a ghost and psychic")
            await client.send(data)
            return
        #Send loading message
        await self.broadcast("loading", True)
        await asyncio.sleep(.1)
        #Check album IDs and lengths
        try:
            album_lengths = [len(self.im.get_album(src).images) for src in data["message"]]
        except:
            data = self.makeData("reject", "Make sure the Imgur album IDs are valid")
            await client.send(data)
            await self.broadcast("loading", False)
            return
        for album_length in album_lengths:
            if(album_length < len(self.psychics) + 3):
                data = self.makeData("reject", "Make sure the Imgur albums have enough images (number of psychics + 3)")
                await client.send(data)
                await self.broadcast("loading", False)
                return
        #Start game
        await self.broadcast("user_list", self._userList())
        await self.sendClientIds()
        self.game = Game(self.num_psychics, album_lengths)
        await self.broadcast("image_links", await self.getImageLinks(data["message"], self.game.cards))
        await self.broadcast("stories", self.game.stories)
        await self.broadcast("state", self.game.state)
        await self.broadcast("start", self.game.cards)
        await self.broadcast("loading", False)
        await self.systemMessage("Game started.")
        await self.ghost.send(self.makeData("ghost_hand", self.game.ghost.hand))
        

    async def getImageLinks(self, album_sources, cards):
        def fix_links(link):
            url, extension = link.rsplit(".", 1)
            # if extension not in ["gif", "png", "jpg", "jpeg"]:
            #     extension = ".gif"
            # url += "_d"
            return url + "." + extension
        imageLinks = {}
        albums = [self.im.get_album(src) for src in album_sources]
        imageLinks['dreams'] = {i: fix_links(image.link) for i, image in enumerate(albums[0].images)}
        suspectLinks= {i: fix_links(albums[1].images[i].link) for i in cards['suspects']}
        placeLinks = {i: fix_links(albums[2].images[i].link) for i in cards['places']}
        thingLinks= {i: fix_links(albums[3].images[i].link) for i in cards['things']}
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
        if self.game and self.game.sendDreams(psychic, dreams):
            await self.broadcast("state", self.game.state)
            await self.ghost.send(self.makeData("ghost_hand", self.game.ghost.hand))
        else:
            await client.send(self.makeData("reject", "invalid action"))  

    async def useRaven(self, client, data):
        ''' Callback when ghost user sends a "useRaven" message
            If there are raven uses remaining (there should be), ghost will have designated dreams replaced
        '''
        dreams = data["message"]["dreams"]
        if self.game and self.game.useRaven(dreams):
            await self.broadcast("state", self.game.state)
            await self.ghost.send(self.makeData("ghost_hand", self.game.ghost.hand))
            await self.systemMessage("CAW CAW! (%i raven(s) remaining)"%(self.game.ravens))
        else:
            await client.send(self.makeData("reject", "invalid action"))  

    async def makeGuess(self, client, data):
        ''' Callback when psychic user sends a "makeGuess" message
            Updates the game state and broadcasts to all users
            If all users have made guesses, perform seance and start next turn
        '''
        psychic = self.psychics.index(client)
        guess = data["message"]["guess"]
        if self.game and self.game.makeGuess(psychic, guess):
            if self.game.doneGuessing():
                self.game.evaluateGuesses()
            await self.broadcast("state", self.game.state)
            if self.game.isGameOver():
                self.game = None
        else:
            await client.send(self.makeData("reject", "invalid action")) 

    async def handleChatMessage(self, client, data):
        ''' Callback when user sends "setRole" message
            Sets self.ghost to client or adds client to self.psychics
            Broadcasts updated user list
        '''
        message = data["message"]["text"]
        user = self.usernames[client]
        m_type = "ghost" if client==self.ghost else "psychic"
        chat_message = {"text": message, "user": user, "type":m_type}
        await self.broadcast("chat_message", chat_message)

    async def systemMessage(self, message):
        '''Broadcasts a message from the system to indicate game status'''
        chat_message = {"text": message, "user": "System", "type":"system"}
        await self.broadcast("chat_message", chat_message)


    def makeData(self, d_type, message=""):
        ''' Returns a json message with type and message '''
        return js.dumps({"type": d_type, "message": message})

    async def sendClientIds(self):
        for i, psychic in enumerate(self.psychics):
            data_out = self.makeData("client_id", i)
            await psychic.send(data_out)
        if self.ghost:
            data_out = self.makeData("client_id", "ghost")
            await self.ghost.send(data_out)

    async def broadcast(self, d_type, data = {}, psychics=False):
        ''' Sends a message to all users in the room
            Can choose to exclude the ghost using the "psychics" argument
        '''
        receivers = self.clients_list
        for receiver in receivers:
            try:
                data_out = self.makeData(d_type, data)
                await receiver.send(data_out)
            except:
                pass
            #     await self.leave(receiver)

    
    def _userList(self):
        ''' Returns a list of each user along with their role (psychic, ghost, other) '''
        user_list = {}
        for i, client in enumerate(self.clients_list):
            if client == self.ghost:
                user_list[i] = {'name': self.usernames[client], "role": "Ghost", "pid": -1}
            elif client in self.psychics:
                user_list[i] = {'name': self.usernames[client], "role": "Psychic", "pid": self.psychics.index(client)}
            else:
                user_list[i] = {'name': self.usernames[client], "role": "", "pid": -1}
        return user_list

    @property
    def full(self):
        return len(self.clients_list)>6

    @property
    def empty(self):
        return len(self.clients_list)==0

    @property
    def num_psychics(self):
        return len(self.psychics)
    

rooms = {}
all_clients = {}

@application.route('/')
async def index(request):
    return await file('build/index.html')

@application.websocket('/game')
async def feed(request, ws):
    while True:
        try:
            data = await ws.recv()
        except Exception as e:
            if ws in all_clients and all_clients[ws]:
                if all_clients[ws] in rooms:
                    await rooms[all_clients[ws]].leave(ws)
                    if rooms[all_clients[ws]].empty:
                        del rooms[all_clients[ws]]
                del all_clients[ws]
            break
        else: 
            data = js.loads(data)  
            if data['type'] == "join":
                if data["message"]["roomname"] in rooms and rooms[data["message"]["roomname"]].game != None and rooms[data["message"]["roomname"]].game.status == "ongoing":
                    await ws.send(js.dumps({"type": "reject", "message": "The game has already started"}))
                elif data["message"]["roomname"] in rooms and rooms[data["message"]["roomname"]].num_psychics >=6:
                    await ws.send(js.dumps({"type": "reject", "message": "Room full"}))
                elif len(data["message"]["roomname"]) == 0 or len(data["message"]["username"])==0:
                    await ws.send(js.dumps({"type": "reject", "message": "Please choose a username and room name"}))
                else:
                    if data["message"]["roomname"] not in rooms: 
                        rooms[data["message"]["roomname"]] = Room(data["message"]["roomname"])
                    all_clients[ws] = data['message']["roomname"]
                    await rooms[data["message"]["roomname"]].join(ws, data["message"]["username"])
            elif data['type'] == " ":
                await rooms[all_clients[ws]].leave(ws)
                if rooms[all_clients[ws]].empty:
                    del rooms[all_clients[ws]]
                del all_clients[ws]
            else:
                if ws in all_clients and all_clients[ws] in rooms:
                    await rooms[all_clients[ws]].handleData(ws, data)

if __name__ == '__main__':
    application.run(host="0.0.0.0", 
                    port=os.environ.get('PORT') or 8002, 
                    debug=True)


