'''
This program is a messaging server for messaging clients to connect to in order
to send messages to other clients. The server handles the processing and
distribution of the messages from clients to other clients.
'''
import configparser
import errno
import datetime
import hashlib
import json
import os
import socket
import ssl
import sys
import threading
import time
import tkinter
import tkinter.ttk
import tkinter.messagebox
import tkinter.simpledialog
import typing
import uuid

#local library containing network status constants
from messaging_modules import functions, status

#file constants
SERVER_PROGRAM_DIR = os.path.dirname(os.path.abspath(__file__)) + os.path.sep
SERVER_WORKING_DIR = SERVER_PROGRAM_DIR  + '.server' + os.path.sep
SERVER_DIRECT_DIR = SERVER_WORKING_DIR + 'direct' + os.path.sep
SERVER_ROOM_DIR = SERVER_WORKING_DIR + 'room' + os.path.sep
ROOM_NAME_FILE = SERVER_ROOM_DIR + '_room_names.json'
CONFIG_FILENAME = SERVER_PROGRAM_DIR + 'server_config.ini'
USER_INFO_FILENAME = SERVER_WORKING_DIR + 'users.json'
JSON_FILE_EXT = '.json'

#window constants
TITLE = 'That Messaging Server!'
GEOMETRY = '800x510'
SPACE = '\u00a0'


#timeout constants
SOCKET_RECIEVE_TIMEOUT = 10
EVENT_HANDLER_TIMEOUT = 10
UPDATE_TIMEOUT = 3

#other constants
DATETIME_LOG_FORMAT = '%c'
ENABLE_SOCK_OPTION = 1

#types
CHANNEL_TYPES = typing.Literal['direct', 'room']

#thread locks for files
log_lock = threading.Lock()
user_file_lock = threading.RLock() #re-entrant lock because read_user_file can call write_to_user_file which both acquire the lock
direct_message_lock = threading.Lock()
room_message_lock = threading.Lock()
certificate_file_lock = threading.Lock()
connected_user_list_lock = threading.Lock()
room_name_file_lock = threading.Lock()

#thread events
server_shutdown = threading.Event()
purge_unencrypted_clients = threading.Event()
purge_encrypted_clients = threading.Event()

#client lists
unencrypted_client_list = []
encrypted_client_list = []
connected_user_list = {}

#log function
def log(message: str):
    '''Prints out the message with the date and time prepended and thread locking.
    - message is a string containing message contents.'''
    with log_lock:
        time_string = datetime.datetime.now().strftime(DATETIME_LOG_FORMAT)
        print(f'[{time_string}]: {message}')

#file structure functions
def fix_missing_server_folders():
    '''Checks for critical folder structures and repairs them if missing.'''
    try:
        if not os.path.isdir(SERVER_WORKING_DIR):
            log(f'{SERVER_WORKING_DIR} is missing, repairing...')
            os.mkdir(SERVER_WORKING_DIR)

        if not os.path.isdir(SERVER_DIRECT_DIR):
            log(f'{SERVER_DIRECT_DIR} is missing, repairing...')
            os.mkdir(SERVER_DIRECT_DIR)

        if not os.path.isdir(SERVER_ROOM_DIR):
            log(f'{SERVER_ROOM_DIR} is missing, repairing...')
            os.mkdir(SERVER_ROOM_DIR)

    except OSError as e:
        log(f'File structure creation error! {e}')
        exit(errno.EPERM)

def read_config_file():
    '''Reads out the configuration file to configure the server operation.
    For information about generating a certificate (self-signed), visit https://docs.python.org/3/library/ssl.html#self-signed-certificates'''
    config = configparser.ConfigParser()
    # set up default values in case of fallback needed due to no config file
    DEFAULT_NET_CONFIG = {'IPAddress':'127.0.0.1',
                         'TCPPort':status.DEFAULT_SERVER_PORT,
                         'SecureTCPPort':38120,
                         'NetworkDiscoveryEnabled':True,
                         'MaxSocketBacklog':5,
                         'MaxSecureBacklog': 5,
                         'MaxSocketConnections': 10,
                         'MaxSecureConnections': 10}
    
    DEFAULT_CERT_CONFIG = {'Certificate':'./server.crt', 'PrivateKey':'./server.key', 'CommonName':'message_server'}

    config['Network'] = DEFAULT_NET_CONFIG
    config['Certificate'] = DEFAULT_CERT_CONFIG

    #loading in configuration overwrites the defaults set above, since most recent takes precedence
    if os.path.isfile(CONFIG_FILENAME):
        log(f'Reading configuration file {CONFIG_FILENAME}')
        config.read(CONFIG_FILENAME)
    else:
        #if the config file is missing, create so server operator can configure the server
        log(f'Configuration file {CONFIG_FILENAME} missing, repairing...')
        with open(CONFIG_FILENAME, 'w') as config_file:
            config.write(config_file)

    #check if datatypes are correct
    try:
        #Network configuration
        ip_address = config['Network'].get('IPAddress')
        tcp_port = config['Network'].getint('TCPPort')
        tls_port = config['Network'].getint('SecureTCPPort')
        enable_net_discovery = config['Network'].getboolean('NetworkDiscoveryEnabled')
        max_sock_backlog = config['Network'].getint('MaxSocketBacklog')
        max_sec_backlog = config['Network'].getint('MaxSecureBacklog')
        max_sock_conn = config['Network'].getint('MaxSocketConnections')
        max_sec_conn = config['Network'].getint('MaxSecureConnections')
        #Certificate configuration
        cert_public_file = os.path.abspath(config['Certificate'].get('Certificate'))
        cert_private_key = os.path.abspath(config['Certificate'].get('PrivateKey'))
        cert_common_name = config['Certificate'].get('CommonName')
    except ValueError as e: # datatypes aren't correct, so exit
        log(f'Configuration Error! {e}')
        exit(errno.EPERM)

    #Check if configuration is valid, otherwise exit
    if not (functions.is_port_valid(tcp_port) and functions.is_port_valid(tls_port)):
        log(f'ERROR! Invalid Configured Port! Must be between {status.MIN_PORT} and {status.MAX_PORT}!')
        exit(errno.ERANGE)
    elif tcp_port == tls_port:
        log('ERROR! The TCP and TLS ports cannot be the same!')
        exit(errno.EINVAL)
    elif tcp_port == status.SERVER_DISCOVERY_PORT or tls_port == status.SERVER_DISCOVERY_PORT:
        log(f'ERROR! The TCP and/or TLS port cannot be {status.SERVER_DISCOVERY_PORT}!')
        exit(errno.EINVAL)
    elif tcp_port == status.CLIENT_DISCOVERY_PORT or tls_port == status.CLIENT_DISCOVERY_PORT:
            log(f'ERROR! The TCP and/or TLS port cannot be {status.CLIENT_DISCOVERY_PORT}!')
            exit(errno.EINVAL)
    elif functions.is_any_int_negative([max_sock_backlog, max_sec_backlog, max_sock_conn, max_sec_conn]):
        log('ERROR! Invalid Configured maximum, cannot be negative!')
        exit(errno.ERANGE)
    elif not os.path.isfile(cert_public_file) or not os.path.isfile(cert_private_key):
        log('ERROR! Certificate and/or Private Keys do not exist, so cannot configure TLS!')
        exit(errno.ENOENT)

    return ip_address, tcp_port, tls_port, enable_net_discovery, max_sock_backlog, max_sec_backlog, max_sock_conn, max_sec_conn, cert_public_file, cert_private_key, cert_common_name
    
def read_certificate_file(cert_filename: str):
    '''Reads out the certificate file for TLS socket communication with clients.
    - cert_file should be a path-like string navigating to the file containing the certificate public key.
    For information about generating a certificate (self-signed), visit https://docs.python.org/3/library/ssl.html#self-signed-certificates'''
    cert_contents = ''
    try:
        with open(cert_filename, 'r') as cert_file:
            cert_contents = cert_file.read()
        log('Read out certificate file.')
        return cert_contents
    except FileNotFoundError:
        log('ERROR! Cannot find certificate file!')
        return

def get_list_channels(type_channel: CHANNEL_TYPES):
    '''Get the list of channels from either the direct or room channel folders.
    - type_channel is either 'direct' or 'room'.'''
    #initialise the channels
    channels = []
    match type_channel:
        case status.CHANNEL_TYPE_DIRECT:
            #get the list of files
            files = os.listdir(SERVER_DIRECT_DIR)
            for file in files:
                #if the uuids are valid, they should be accepted by the UUID class, otherwise the UUID class will raise ValueError.
                test_uuid = file.strip(JSON_FILE_EXT)
                if functions.check_uuid_valid(test_uuid):
                    channels.append(test_uuid)
        case status.CHANNEL_TYPE_ROOM:
            files = os.listdir(SERVER_ROOM_DIR)
            for file in files:
                #if the uuids are valid, they should be accepted by the UUID class, otherwise the UUID class will raise ValueError.
                test_uuid = file.strip(JSON_FILE_EXT)
                if functions.check_uuid_valid(test_uuid):
                    channels.append(test_uuid)
        case _:
            return
    return channels

def get_messages_from_channel(type_channel: CHANNEL_TYPES, id:str, from_time:float=0):
    '''Get the messages from a direct or room channel.
    - type_channel should be either 'direct' or 'room'. 
    - id should be a uuid.UUID version 4.
    - from_time should be some seconds since the epoch that the messages returned from should be from to current time.'''
    if not functions.check_uuid_valid(id) and id not in get_list_channels(type_channel):
        return
    #initialise variables to avoid UnboundLocalError
    messages = {}
    contents = ''
    #chack if file exists
    file = SERVER_DIRECT_DIR+id+JSON_FILE_EXT if type_channel == status.CHANNEL_TYPE_DIRECT else SERVER_ROOM_DIR+id+JSON_FILE_EXT
    if not os.path.isfile(file):
        return
    #check channel type to read out
    if type_channel == status.CHANNEL_TYPE_DIRECT:
        with direct_message_lock:
            with open(file) as message_file:
                contents = message_file.read()
    else:
        with room_message_lock:
            with open(file) as message_file:
                contents = message_file.read()
    result = []
    #parse the json into a dictionary
    try:
        messages = json.loads(contents)
    except json.JSONDecodeError:
        return
    #if there is no set from_time, return all messages
    if from_time == 0:
        try:
            return messages.values(), float(list(messages.keys())[-1])
        except IndexError:
            return {}, 0

    latest_time = 0

    #cycle through messages, as if they are before from_time or invalid, remove them from returned list
    for time in messages.keys():
        try:
            if float(time) > from_time:
                result.append(messages[time])
                latest_time = float(time)
        except ValueError:
            continue

    return result, latest_time

def write_to_message_file(id: str, message: str, type_channel: CHANNEL_TYPES):
    '''Write a messsage to a channel file.
    - file is a path-like string
    - messsage is the message to save.'''
    #form the file string
    file = SERVER_DIRECT_DIR+id+JSON_FILE_EXT if type_channel == status.CHANNEL_TYPE_DIRECT else SERVER_ROOM_DIR+id+JSON_FILE_EXT
    messages = {} 
    if id in get_list_channels(type_channel):
        with open(file, 'r') as message_file:
            try:
                #if the file previously exists, 
                    messages = json.loads(message_file.read())
            except json.JSONDecodeError:
                messages = {}
            messages.update({time.time():message})
    with open(file, 'w') as message_file:
        message_file.write(json.dumps(messages))

def save_message_to_channel(type_channel: CHANNEL_TYPES, id:str, message:str):
    '''Save messages to a channel.
    - type_channel should be either 'direct' or 'room'. 
    - id should be a uuid.UUID version 4.
    - message should be a message string to save.'''
    #if the uuid isn't valid, it cant be read by get_messages_from_channel, so return
    if not functions.check_uuid_valid(id):
        return
    #acquire the lock relevant to the channel type and write out
    if type_channel == status.CHANNEL_TYPE_DIRECT:
        with direct_message_lock:
            write_to_message_file(id, message, type_channel)
    else:
        with room_message_lock:
            write_to_message_file(id, message, type_channel)

def write_to_user_file(id:str, user_info:dict):
    '''Updates/Creates the user information file.
    - id should be a string in the format of UUID version 4
    - user_info should be a dictionary with the format of: {'username':..., 'directs':[{...:...},...], 'rooms':[{...:...},...],'banned':True/False}
      that stores the user information.'''
    if not functions.check_uuid_valid(id):
        return
    #initialise the disctionary to prepare to serialise and write
    users = {}
    try:
        #read out the file if it exists and get the info to update, if it exists
        with user_file_lock:
            with open(USER_INFO_FILENAME) as userfile:
                contents = userfile.read()
                if contents:
                    try:
                        users = json.loads(contents)
                    except json.JSONDecodeError:
                        users = {}
    except FileNotFoundError:
        users = {}
    try:
        #write the serialised data to the user info file
        users.update({id:user_info})
        with user_file_lock:
            with open(USER_INFO_FILENAME, 'w') as userfile:
                userfile.write(json.dumps(users))
            return True
    except OSError:
        return

def read_user_file():
    '''Reads out the user file.'''
    try:
        with user_file_lock:
            with open(USER_INFO_FILENAME) as userfile:
                contents = userfile.read()
                #if it is possible to get the user from the file, get it, otherwise make a new user
                if contents:
                    try:
                        users = json.loads(contents)
                        return users
                    except json.JSONDecodeError:
                        return
    except FileNotFoundError:
        return

def get_from_user_file(id: str):
    '''Gets information about a user from the user info file.
    - id is a UUID 4'''
    default = {status.DATA_USERNAME:id, 
               status.DATA_DIRECTS:[], 
               status.DATA_ROOMS:[],
               status.DATA_BANNED:False}
    user = {}
    if not functions.check_uuid_valid(id):
        return
    try:
        with user_file_lock:
            #read out the file if it exists and get the info to update, if it exists
            with open(USER_INFO_FILENAME) as userfile:
                contents = userfile.read()
                #if it is possible to get the user from the file, get it, otherwise make a new user
                if contents:
                    try:
                        users = json.loads(contents)
                    except json.JSONDecodeError:
                        users = {}
                    try:
                        user = users[id]
                    except KeyError:
                        write_to_user_file(id, default)
                else:
                    write_to_user_file(id, default)
    except FileNotFoundError:
        write_to_user_file(id, default)
    #if the user dictionary is not filled, return the default info
    if not user:
        user = default
    return user

def get_users_in_channel(channel_type: CHANNEL_TYPES, channel_id: str):
    '''Gets the users in a channel by checking whether their joined channel list contains the channel id.
    - channel_type should be the type of channel.
    - channel_id should be a UUID of a channel.'''
    #get the user information and iterate through the users and return the ones that are in the channel
    select_type = None
    #user information dict keys are not the same as the channel types values
    if channel_type == status.CHANNEL_TYPE_DIRECT:
        select_type = status.DATA_DIRECTS
    elif channel_type == status.CHANNEL_TYPE_ROOM:
        select_type = status.DATA_ROOMS
    else:
        return
    if not functions.check_uuid_valid(channel_id):
        return
    #iterate through list and return users that are in the channel
    users = {}
    user_list = read_user_file()
    for ouid, info in user_list.items():
        if channel_id in info[select_type]:
            users.update({ouid:info[status.DATA_USERNAME]})
    return users

def get_room_name(id: str):
    '''Gets the room name from the room name file.
    - id should be a uuid of a room.'''
    if not functions.check_uuid_valid(id):
        return
    try:
        with room_name_file_lock:
            with open(ROOM_NAME_FILE) as namefile:
                contents = namefile.read()
                rooms = json.loads(contents)
                return rooms[id]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return

def save_room_name(id:str, name: str):
    '''Saves a room name to the room name file.
    - id should be the uuid of a room.
    - name should be a string, which will be truncated if it is longer than the max room name length.'''
    if len(name) > status.ROOM_NAME_MAX_LEN:
        name = name[:status.ROOM_NAME_MAX_LEN]
    if not functions.check_uuid_valid(id):
        return
    with room_name_file_lock:
        with open(ROOM_NAME_FILE, 'w') as namefile_w:
            rooms = {}
            try:
                with open(ROOM_NAME_FILE) as namefile_r:
                    rooms = json.loads(namefile_r.read())
            except (FileNotFoundError, json.JSONDecodeError):
                rooms = {}
            rooms.update({id:name})
            namefile_w.write(json.dumps(rooms))


#connection handler functions
def unencrypted_client_handler(conn: socket.socket, addr):
    '''Handles a single connection stream from an unencrypted socket client.
    - conn is an existing connection as a socket object.
    - addr is the address data of the connection.'''
    #set a timeout so the recv is not blocking indefinitely and any conditions can be chacked.
    conn.settimeout(SOCKET_RECIEVE_TIMEOUT)

    buffer = functions.get_raw_buffer(conn)

    #function returns none if there is a connection issue.
    if not buffer:
        log(f'ERROR: Connection issue with peer {addr}.')
        return

    #If there is a connection issue, or no inital packet
    if len(buffer) == 0 or not buffer:
        log(f'Connection with peer {addr} has timed out without a request to join the server.')
        conn.close()
        return
    #The first packet should always be an attempt to join packet.
    try:
        if buffer[0][status.PACKET_STATUS] != status.ATTEMPT_SERVER_JOIN:
            log(f'Peer {addr} did not initiate the connection with a join packet.')
            conn.close()
            return
    except KeyError:
        log(f'Peer {addr} sent an invalid join packet.')
        conn.close()
        return
    #reply with success
    functions.send_conn_packet(conn, status.SERVER_JOINED)
    log(f'Peer {addr} has joined the server.')
    #remove first packet from buffer, so it does not get processed after
    buffer.pop(0)

    while not purge_unencrypted_clients.is_set():
        #gets data from the socket buffer to repopulate the buffer list if empty
        if len(buffer) == 0:
            recieved_packets = functions.get_raw_buffer(conn)
            
            if recieved_packets == None: # returned by get_raw_buffer and parse_conn_buffer when there is a connection issue
                log(f'Connection with peer {addr} has broken.')
                break
            
            for packet in recieved_packets:
                buffer.append(packet)

        if len(buffer) == 0: #if the buffer is still empty after getting the packets from the socket buffer, try again
            continue

        #Get the first packet from the buffer
        packet = buffer[0]
        buffer.pop(0)

        if not functions.check_packet_initial_contents(packet):
            log(f'Peer {addr} sent a packet missing critical data!')
            functions.send_conn_packet(conn, status.BAD_REQUEST)
            continue

        packet_status = packet[status.PACKET_STATUS]

        match packet_status:
            case status.GET_SERVER_INFO: #when client requests server info, reply with TLS port and common name for the certificate
                payload = {status.DATA_TLS:TLS_PORT, status.DATA_COMMON_NAME:COMMON_NAME}
                functions.send_conn_packet(conn, status.REPLY_SERVER_INFO, payload)
            case status.GET_TLS_CERT:
                certificate = read_certificate_file(PUBLIC_CERT_FILE)
                if not certificate:
                    log('WARNING: No certificate to provide!')
                    functions.send_conn_packet(conn, status.OPERATION_FAILURE)
                else:
                    functions.send_conn_packet(conn, status.REPLY_TLS_CERT, certificate)
            case status.CLOSE_SOCKET:
                log(f'Peer {addr} has closed the connection.')
                break
            case status.BAD_REQUEST:
                log(f'Peer {addr} has alerted the server of a bad request.')
                continue
            case _:
                log(f'Peer {addr} sent a packet with an invalid status.')
                functions.send_conn_packet(conn, status_code=status.BAD_REQUEST)
    try:
        functions.send_conn_packet(conn, status.SERVER_CLOSED_SOCKET)
    except ConnectionError:
        log(f'Attempted to send socket closed packet to peer {addr}, but no connection.')
    #remove from the unencrypted thread connection list
    unencrypted_client_list.remove(addr)
    conn.close()
    log(f'The connection with peer {addr} has been closed.')

def encrypted_client_handler(conn: socket.socket, addr):
    '''Handles a single connection stream from an encrypted socket client.
    - conn is an existing connection as a socket object.
    - addr is the address data of the connection.'''
    global connected_user_list
    #set a timeout so the recv is not blocking indefinitely and any conditions can be chacked.
    conn.settimeout(SOCKET_RECIEVE_TIMEOUT)
    #intialise the id for use
    uid = ''
    #get input from buffer
    buffer = functions.get_raw_buffer(conn)

    #function returns none if there is a connection issue.
    if not buffer:
        log(f'ERROR: Encrypted connection issue with peer {addr}.')
        return

    #If there is a connection issue, or no inital packet
    if len(buffer) == 0 or not buffer:
        log(f'Encrypted connection with peer {addr} has timed out without a request to join the server.')
        conn.close()
        return
    #The first packet should always be an attempt to join packet.
    try:
        if buffer[0][status.PACKET_STATUS] != status.ATTEMPT_SERVER_JOIN:
            log(f'Encrypted peer {addr} did not initiate the connection with a join packet.')
            conn.close()
            return
        uid = buffer[0][status.PACKET_DATA][status.DATA_ID]
    except KeyError:
        log(f'Encrypted peer {addr} sent an invalid join packet.')
        conn.close()
        return
    #get the user information
    user = get_from_user_file(uid)

    #if they are banned, alert the client and close the connection.
    if user[status.DATA_BANNED]:
        log(f'Banned client {user[status.DATA_USERNAME]} ({uid}) attempted to join the server from {addr}.')
        functions.send_conn_packet(conn, status.REFUSED_JOIN)
        conn.close()
        return
    #reply with success if otherwise
    functions.send_conn_packet(conn, status.SERVER_JOINED)
    log(f'Client {user[status.DATA_USERNAME]} ({uid}) @ {addr} has joined the server.')
    #remove first packet from buffer, so it does not get processed after
    buffer.pop(0)
    #update the connected user dictionary to reflect the connection
    with connected_user_list_lock:
        connected_user_list.update({uid:user})

    encrypted_client_list.append(addr)

    while not purge_encrypted_clients.is_set():
        #check if the user is banned, and disconnect if so
        if connected_user_list[uid][status.DATA_BANNED]:
            log(f'User {uid} has been banned, closing the connection.')
            functions.send_conn_packet(conn, status.SERVER_CLOSED_SOCKET)
            conn.close()
            return
        #gets data from the socket buffer to repopulate the buffer list if empty
        if len(buffer) == 0:
            recieved_packets = functions.get_raw_buffer(conn)
            
            if recieved_packets == None: # returned by get_raw_buffer and parse_conn_buffer when there is a connection issue
                log(f'Encrypted connection with peer {addr} has broken.')
                break
            
            for packet in recieved_packets:
                buffer.append(packet)

        if len(buffer) == 0: #if the buffer is still empty after getting the packets from the socket buffer, try again
            continue

        #Get the first packet from the buffer
        packet = buffer[0]
        buffer.pop(0)

        if not functions.check_packet_initial_contents(packet):
            log(f'Peer {addr} sent a packet missing critical data!')
            functions.send_conn_packet(conn, status.BAD_REQUEST)
            continue

        packet_status = packet[status.PACKET_STATUS]

        try:
            match packet_status:
                case status.SET_USERNAME:
                    #set the new username from the packet data
                    user_info = get_from_user_file(uid)
                    new_username = packet[status.PACKET_DATA][status.DATA_USERNAME]
                    user_info.update({status.DATA_USERNAME:new_username})
                    write_to_user_file(uid, user_info)
                    log(f'User {uid} has changed their username to {new_username}')
                    functions.send_conn_packet(conn, status.OPERATION_SUCCESS)          
                case status.GET_USER_INFO:
                    #attempt to sync the connected_user_list when a client wants to check their user info
                    user_info = get_from_user_file(uid)
                    direct_info = {}
                    for direct in user_info[status.DATA_DIRECTS]: #compile a dictionary of the direct messages, the other user and name
                        other_user = []
                        users = read_user_file()
                        for user_id, info in users.items():
                            if user_id == uid:
                                continue
                            if direct in info[status.DATA_DIRECTS]:
                                other_user = [user_id, info[status.DATA_USERNAME]]
                                break
                        if other_user:
                            direct_info.update({direct:other_user})
                        else:
                            direct_info.update({direct:None})
                    room_info = {}
                    for room in user_info[status.DATA_ROOMS]: #compile a dictionary of rooms and their name
                        name = get_room_name(room)
                        if not name:
                            name = room
                        room_info.update({room:name})
                    #send the info to the user in yet another dictionary
                    packet = {status.DATA_USERNAME:user_info[status.DATA_USERNAME], status.DATA_DIRECTS:direct_info, status.DATA_ROOMS:room_info}
                    functions.send_conn_packet(conn, status.REPLY_USER_INFO, packet)
                    with connected_user_list_lock:
                        connected_user_list[uid] = user_info
                case status.GET_USER_LIST:
                    #get a list of the users in a channel using the function that does that
                    channel_type = packet[status.PACKET_DATA][status.DATA_TYPE]
                    channel_id = packet[status.PACKET_DATA][status.DATA_ID]
                    users = get_users_in_channel(channel_type, channel_id)
                    if not users:
                        functions.send_conn_packet(conn, status.BAD_REQUEST)
                        continue
                    functions.send_conn_packet(conn, status.REPLY_USER_LIST, users)
                    log(f'User {uid} has gotten the user list of {channel_id} ({channel_type})')
                case status.CREATE_DIRECT:
                    #create a direct message channel by finding the other user and adding a common new channel id to both users' direct channel lists
                    other_user_id = packet[status.PACKET_DATA][status.DATA_ID]
                    users = read_user_file()
                    if other_user_id not in users.keys():
                        functions.send_conn_packet(conn, status.OPERATION_FAILURE, 'No such user.')
                        continue
                    skip = False #prevent UnboundLocalError, used if there is a common direct message between two users already, why need a new one?
                    for direct in users[other_user_id][status.DATA_DIRECTS]:
                        if direct in users[uid][status.DATA_DIRECTS]:
                            functions.send_conn_packet(conn, status.OPERATION_FAILURE, f'Direct Message already exists with {other_user_id}.')
                            skip = True 
                            break
                    if skip:
                        continue
                    #create the new id and add to direct message list of both users
                    new_channel_id = str(uuid.uuid4())
                    for user_id in (uid, other_user_id):
                        user = users[user_id]
                        user[status.DATA_DIRECTS].append(new_channel_id)
                        write_to_user_file(user_id, user)
                    functions.send_conn_packet(conn, status.OPERATION_SUCCESS)
                    log(f'User {uid} has created a direct message ({new_channel_id}) with user {other_user_id}.')
                case status.CREATE_ROOM:
                    #get the room name from the creator and create a room, register the name with the name file, and add to creator's room list
                    new_room_name = packet[status.PACKET_DATA][status.DATA_NAME]
                    users = read_user_file()
                    new_channel_id = str(uuid.uuid4())
                    user = users[uid]
                    user[status.DATA_ROOMS].append(new_channel_id)
                    write_to_user_file(uid, user)
                    save_room_name(new_channel_id, new_room_name)
                    functions.send_conn_packet(conn, status.OPERATION_SUCCESS)
                    log(f'User {uid} has created a room called {new_room_name} ({new_channel_id}).')
                case status.SEND_MESSAGE:
                    #get the message, format the message, save the message
                    channel_type = packet[status.PACKET_DATA][status.DATA_TYPE]
                    channel_id = packet[status.PACKET_DATA][status.DATA_ID]
                    message = packet[status.PACKET_DATA][status.DATA_MESSAGE]
                    message_save = f'<{connected_user_list[uid][status.DATA_USERNAME]}> {message}'
                    write_to_message_file(channel_id, message_save, channel_type)
                    log(f'User {uid} has sent a message to {channel_id} ({channel_type})')
                case status.JOIN_ROOM:
                    #add the room id if the server has the room
                    room_id = packet[status.PACKET_DATA][status.DATA_ID].strip()
                    if room_id not in get_list_channels(status.CHANNEL_TYPE_ROOM) and not get_room_name(room_id): #the room exists if either: it has a file containing its messages, or is registered in the name file
                        functions.send_conn_packet(conn, status.OPERATION_FAILURE, 'No such room!')
                        continue
                    user = get_from_user_file(uid)
                    user[status.DATA_ROOMS].append(room_id)
                    write_to_user_file(uid, user)
                    functions.send_conn_packet(conn, status.OPERATION_SUCCESS)
                case status.LEAVE_CHANNEL:
                    #delete the channel from the respective channel of the user if they have that id
                    user = get_from_user_file(uid)
                    channel_type = packet[status.PACKET_DATA][status.DATA_TYPE]
                    channel_id = packet[status.PACKET_DATA][status.DATA_ID]
                    try:
                        if channel_type == status.CHANNEL_TYPE_DIRECT:
                            user[status.DATA_DIRECTS].remove(channel_id)
                        elif channel_type == status.CHANNEL_TYPE_ROOM:
                            user[status.DATA_ROOMS].remove(channel_id)
                        else:
                            functions.send_conn_packet(conn, status.BAD_REQUEST)
                            continue
                    except ValueError:
                        functions.send_conn_packet(conn, status.OPERATION_FAILURE, 'No such channel!')
                    write_to_user_file(uid, user)
                    functions.send_conn_packet(conn, status.OPERATION_SUCCESS)
                case status.GET_MESSAGES:
                    #get the messages
                    channel_type = packet[status.PACKET_DATA][status.DATA_TYPE]
                    channel_id = packet[status.PACKET_DATA][status.DATA_ID]
                    from_time = packet[status.PACKET_DATA][status.DATA_FROM]
                    messages = get_messages_from_channel(channel_type, channel_id, from_time)
                    if messages: #compile a list of the messages and send
                        msg_list, latest_time = messages
                        packet = {status.DATA_MESSAGE:msg_list, status.DATA_FROM:latest_time, status.DATA_TYPE: channel_type, status.DATA_ID:channel_id}
                        functions.send_conn_packet(conn, status.REPLY_MESSAGES, packet)
                        log(f'User {uid} got the messages from channel {channel_id} ({channel_type})')
                case status.CLOSE_SOCKET:
                    log(f'Encrypted peer {addr} has closed the connection.')
                    break
                case status.BAD_REQUEST:
                    log(f'Encrypted peer {addr} has alerted the server of a bad request.')
                    continue
                case _:
                    log(f'Encrypted peer {addr} sent a packet with an invalid status.')
                    functions.send_conn_packet(conn, status_code=status.BAD_REQUEST)
        except KeyError:
           functions.send_conn_packet(conn, status.BAD_REQUEST)
    try:
        functions.send_conn_packet(conn, status.SERVER_CLOSED_SOCKET)
    except (ConnectionError, ssl.SSLError):
        log(f'Attempted to send socket closed packet to encrypted peer {addr}, but no connection.')
    #remove from the encrypted thread connection list and connected_user_list
    encrypted_client_list.remove(addr)
    with connected_user_list_lock:
        del connected_user_list[uid]
    conn.close()
    log(f'The encrypted connection with peer {addr} has been closed.')
    
#socket listener functions
def unencrypted_socket_listener(sock:socket.socket):
    '''Unencrypted socket listener which accepts incoming connections and spawns a thread with a handler.
    - sock is a bound, listening socket object'''
    log('Unencrypted socket thread started.')
    #since the socket timeout is set, the accept will not block indefinitely, and the condition will be checked after the timeout elapses
    while not server_shutdown.is_set():
        try:
            if len(unencrypted_client_list) >= MAX_SOCK_CONN:
                continue
            conn, addr = sock.accept()
            log(f'New unencrypted connection: {addr}')
            new_client_thread = threading.Thread(target=unencrypted_client_handler, args=[conn, addr])
            new_client_thread.start()
            unencrypted_client_list.append(addr)
        except TimeoutError:
            continue
        except ConnectionError as e:
            log(f'Connection with peer {addr} has produced an error: {e}')
    log('The unencrypted socket is now shutting down.')
    sock.close()

def encrypted_socket_listener(secure_sock: ssl.SSLSocket):
    '''Encrypted socket listener which accepts incoming connections and spawns a thread with a handler.
    - secure_sock is a socket object with a TLS wrapper.'''
    log('Encrypted socket thread started.')
    #since the socket timeout is set, the accept will not block indefinitely, and the condition will be checked after the timeout elapses
    while not server_shutdown.is_set():
        try:
            if len(encrypted_client_list) >= MAX_SECURE_CONN:
                continue
            conn, addr = secure_sock.accept()
            cipher = conn.cipher() #used for cool nerdy stuff in the log
            log(f'New encrypted connection: {addr} (cipher suite: {cipher[0]} TLS version: {cipher[1]} secret bits: {cipher[2]})')
            new_client_thread = threading.Thread(target=encrypted_client_handler, args=[conn, addr])
            new_client_thread.start()
        except TimeoutError:
            continue
        except ConnectionError as e:
            log(f'Connection with peer has produced an error: {e}')
        except ssl.SSLError as e:
            log(f'Connection with peer has a TLS issue: {e}')
    log('The encrypted socket is now shutting down.')
    secure_sock.close()

def network_discovery_listener(discovery_sock: socket.socket):
    '''Socket listener which replies to network discovery requests made by clients.
    - discovery_sock should be a socket with SOCK_DGRAM'''
    log('Network Discovery listener enabled and listening.')
    while not server_shutdown.is_set():
        try:
            #attempt to recieve a network discovery packet
            recieved, addr = discovery_sock.recvfrom(status.DEFAULT_BUFFER_SIZE)
            buffer = functions.parse_conn_buffer(recieved.decode())
            #If the socket has a connection issue, check status
            if not buffer:
                log(f'Could not get discovery attempt from {addr}.')
                continue
            #if the buffer is still empty after getting, retry
            elif len(buffer) == 0:
                continue
            #Get the first packet and remove from buffer
            packet = buffer[0]
            buffer.pop(0)
            #Check that the packet is a valid discovery attempt
            if not functions.check_packet_initial_contents(packet) or packet[status.PACKET_STATUS] != status.ATTEMPT_NET_DISCOVERY:
                log(f'Peer {addr} sent a bad network discovery packet.')
                functions.send_conn_packet(discovery_sock, status.BAD_REQUEST, addr=addr)
                continue
            #send the data packet
            payload = {status.DATA_PORT:TCP_PORT, status.DATA_COMMON_NAME:COMMON_NAME}
            log(f'Peer {addr} has discovered the server.')
            functions.send_conn_packet(discovery_sock, status.REPLY_NET_DISCOVERY, payload, (addr[0], status.CLIENT_DISCOVERY_PORT))
        except TimeoutError:
            #If the recv times out, re-check whether server_shutdown is set
            continue

    log('Network Discovery listener stopped.')
    discovery_sock.close()

def event_handler_thread():
    '''Handles thread event changes and changes other thread events if needed.'''
    messagebox_title = 'Event'
    log('Event handler thread started.')
    while not server_shutdown.is_set():
        #If the server is on and the operator has set purge_unencrypted_clients, wait for the threads to remove themselves
        #from unencrypted client list, then unset.
        if purge_unencrypted_clients.is_set():
            if len(unencrypted_client_list) == 0:
                tkinter.messagebox.showinfo(messagebox_title, 'Unencrypted client purge complete!')
                purge_unencrypted_clients.clear()
        #If the server is on and the operator has set purge_encrypted_clients, wait for the threads to remove themselves
        #from encrypted client list, then unset.
        if purge_encrypted_clients.is_set():
            if len(encrypted_client_list) == 0:
                tkinter.messagebox.showinfo(messagebox_title, 'Encrypted client purge complete!')
                purge_encrypted_clients.clear()
        #wait some period of time to check above conditions again to  make sure that the event handler thread doesn't gobble up resources
        server_shutdown.wait(EVENT_HANDLER_TIMEOUT)
    log('server_shutdown set, purging all client connections...')
    purge_unencrypted_clients.set()
    purge_encrypted_clients.set()

#window functions
def on_server_shutdown_pressed():
    '''Tkinter event bound to when the server shutdown button is pressed.'''
    messagebox_title = 'Shutdown'
    result = tkinter.messagebox.askyesnocancel(messagebox_title, 'Are you sure you want to shut down the server now?')
    if not result:
        return
    tkinter.messagebox.showwarning(messagebox_title, 'The server is now shutting down!')
    server_shutdown.set()
    root.destroy()

def on_purge_unencrypted_menu_pressed():
    '''Tkinter event bound to when the purge -> unencrypted client button is pressed.'''
    messagebox_title = 'Purge'
    if purge_unencrypted_clients.is_set(): #if already set, useless to set again
        tkinter.messagebox.showerror(messagebox_title, 'The purging of unencrypted clients has not yet finished.')
        return
    result = tkinter.messagebox.askyesnocancel(messagebox_title, 'Are you sure you want to purge the connections of all unencrypted clients?')
    if not result:
        return
    tkinter.messagebox.showwarning(messagebox_title, 'No clients will be able to connect to the server until the purge is complete.')
    purge_unencrypted_clients.set()

def on_purge_encrypted_menu_pressed():
    '''Tkinter event bound to when the purge -> encrypted client button is pressed.'''
    messagebox_title = 'Purge'
    if purge_encrypted_clients.is_set(): #if it is already set, no use setting it again
            tkinter.messagebox.showerror(messagebox_title, 'The purging of encrypted clients has not yet finished.')
            return
    result = tkinter.messagebox.askyesnocancel(messagebox_title, 'Are you sure you want to purge the connections of all encrypted clients?')
    if not result:
        return
    tkinter.messagebox.showwarning(messagebox_title, 'No clients will be able to connect to the server until the purge is complete.')
    purge_encrypted_clients.set()

def on_channel_listbox_select(*event):
    '''Tkinter event bound to when the channel listbox is selected.'''
    try: #get the channel select string and save it as the current room
        selection = channel_select.selection_get()
        if selection not in channel_select.get(status.START, tkinter.END): #if something from another widget is selected, disregard
            return        
        current_channel.set(selection)
        channel_select.selection_clear(tkinter.END)
        last_update_time.set(0)
        #on changing the current channel, clear the old userlist and messages
        messages_view.config(state=tkinter.NORMAL)
        messages_view.delete(1.0, tkinter.END)
        messages_view.config(state=tkinter.DISABLED)
        user_list.config(state=tkinter.NORMAL)
        user_list.delete(1.0, tkinter.END)
        user_list.config(state=tkinter.DISABLED)
    except tkinter.TclError: #TclError when a selection is made without anything to select
        return

def on_ban_user_menu_pressed():
    '''Tkinter event bound to when the moderation -> ban user button is pressed.'''
    global connected_user_list
    messagebox_title = 'Ban User'
    user_id = tkinter.simpledialog.askstring(messagebox_title, 'Enter the UUID of the user to ban:')
    if not user_id:
        return
    elif not functions.check_uuid_valid(user_id):
        tkinter.messagebox.showerror(messagebox_title, 'Not a valid UUID!')
        return
    users = read_user_file()
    if user_id not in users.keys():
        tkinter.messagebox.showerror(messagebox_title, 'No such user!')
        return
    user = users[user_id]
    user[status.DATA_BANNED] = True
    write_to_user_file(user_id, user)
    if user_id in connected_user_list.keys():
        with connected_user_list_lock:
            connected_user_list[user_id][status.DATA_BANNED] = True
    tkinter.messagebox.showinfo(messagebox_title, f'User {user_id} has been banned.')


def on_pardon_user_menu_pressed():
    '''Tkinter event bound to when the moderation -> pardon user button is pressed.'''
    global connected_user_list
    messagebox_title = 'Pardon User'
    user_id = tkinter.simpledialog.askstring(messagebox_title, 'Enter the UUID of the user to ban:')
    if not user_id:
        return
    elif not functions.check_uuid_valid(user_id):
        tkinter.messagebox.showerror(messagebox_title, 'Not a valid UUID!')
        return
    users = read_user_file()
    if user_id not in users.keys():
        tkinter.messagebox.showerror(messagebox_title, 'No such user!')
        return
    user = users[user_id]
    user[status.DATA_BANNED] = False
    write_to_user_file(user_id, user)
    if user_id in connected_user_list.keys():
        with connected_user_list_lock:
            connected_user_list[user_id][status.DATA_BANNED] = False
    tkinter.messagebox.showinfo(messagebox_title, f'User {user_id} has been pardoned.')

def gui_update_handler():
    '''Thread that periodically updates the channel listbox, the messages textbox, and the user list.'''
    log('GUI update handler thread started.')
    last_update_time.set(0)
    while not server_shutdown.is_set():
        #clear and readd all of the channels
        channel_select.delete(status.START, tkinter.END)
        for channel_type in (status.CHANNEL_TYPE_DIRECT, status.CHANNEL_TYPE_ROOM):
            for channel_id in get_list_channels(channel_type):
                channel_select.insert(tkinter.END, channel_type+SPACE+channel_id)
        #if current_room is set, add the messages and users into their respective widgets
        if current_channel.get():
            messages_view.config(state=tkinter.NORMAL)
            channel_type, channel_id = current_channel.get().split(SPACE)
            channel_info = get_messages_from_channel(channel_type, channel_id, last_update_time.get())
            if not channel_info:
                server_shutdown.wait(UPDATE_TIMEOUT)
                continue
            messages, last_message_time = channel_info
            if last_update_time.get() < last_message_time: #if the saved time is less than the time of the latest message, add new messages and save new time
                for message in messages:
                    messages_view.insert(tkinter.END, f'{message}\n')
                last_update_time.set(last_message_time)
            messages_view.config(state=tkinter.DISABLED)
            users = get_users_in_channel(channel_type, channel_id)
            user_list.config(state=tkinter.NORMAL)
            if users: #get the userlist and only change the contents if the user list changes.
                userlist_update = ''
                for user_id, username in users.items():
                    userlist_update += f'{username} ({user_id})\n'
                if user_list.get(1.0, tkinter.END).strip() != userlist_update.strip():
                    user_list.delete(1.0, tkinter.END)
                    user_list.insert(tkinter.END, userlist_update)
            user_list.config(state=tkinter.DISABLED)
        server_shutdown.wait(UPDATE_TIMEOUT) #wait for some period of time to 'cooldown' unless server_shutdown is set
    log('GUI update handler thread stopped.')


if __name__ == '__main__':
    #################
    # Initial Setup #
    #################

    #make sure that the program is running in the program's current folder
    os.chdir(SERVER_PROGRAM_DIR)
    fix_missing_server_folders()
    #Load constants from configuration file
    HOST, TCP_PORT, TLS_PORT, NETWORK_DISCOVERY_ENABLED, MAX_SOCK_BACKLOG, MAX_SECURE_BACKLOG, MAX_SOCK_CONN, MAX_SECURE_CONN, PUBLIC_CERT_FILE, CERT_PRIVATE_KEY, COMMON_NAME = read_config_file()
    log(f'Configuration Loaded: Host:TCPPort/SecureTCPPort: {HOST}:{TCP_PORT}/{TLS_PORT} NetworkDiscoveryEnabled:{NETWORK_DISCOVERY_ENABLED} Max Backlogs: Socket:{MAX_SOCK_BACKLOG}, Secure:{MAX_SECURE_BACKLOG} Max Connections: Socket:{MAX_SOCK_CONN} Secure:{MAX_SECURE_CONN}')
    CERTTIFICATE_HASH = hashlib.sha256(read_certificate_file(PUBLIC_CERT_FILE).encode()).hexdigest()
    log(f'Found certificates at {PUBLIC_CERT_FILE} key:{CERT_PRIVATE_KEY} name:{COMMON_NAME} hash(sha256):{CERTTIFICATE_HASH}')

    #start event handler thread
    event_handler = threading.Thread(target=event_handler_thread)
    event_handler.start()

    #create the unencrypted socket object and hand off to the socket listener thread
    try:
        unencrypted_socket = socket.create_server((HOST, TCP_PORT), backlog=MAX_SOCK_BACKLOG)
        unencrypted_socket.settimeout(SOCKET_RECIEVE_TIMEOUT)
        socket_thread = threading.Thread(target=unencrypted_socket_listener, args=[unencrypted_socket,])
        socket_thread.start()
    except OSError as e:
        log(f'ERROR! {e} Are you sure you configured the IP Address correctly?')

    #create the encrypted socket object and hand it off the the encrypted socket listener thread
    try:
        encrypted_socket = socket.create_server((HOST, TLS_PORT), backlog=MAX_SECURE_BACKLOG)
        encrypted_socket.settimeout(SOCKET_RECIEVE_TIMEOUT)
    except OSError as e:
        log(f'ERROR! {e} Are you sure you configured the IP Address correctly?')

    #Load TLS certificate and private key for encryption
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    try:
        context.load_cert_chain(PUBLIC_CERT_FILE, CERT_PRIVATE_KEY)
    except FileNotFoundError:
        log('ERROR! Could not find certificate files!')
        exit(errno.ENOENT)
    except ssl.SSLError:
        log('ERROR! The certificates are not in PEM format! Are you sure that the certificates are real?')

    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers(status.CIPHERS) #set ciphers to prevent 'bad' ones

    secure_socket = context.wrap_socket(encrypted_socket, server_side=True)

    secure_thread = threading.Thread(target=encrypted_socket_listener, args=[secure_socket,])
    secure_thread.start()

    #create the network discovery listener if enabled
    if NETWORK_DISCOVERY_ENABLED:
        #Set the discovery socket UDP, because TCP handshakes are not needed.
        discovery_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        #bind the socket to the HOST and SERVER_DISCOVERY_PORT
        try:
            discovery_socket.bind((status.ALL_INTERFACES, status.SERVER_DISCOVERY_PORT))
        except OSError as e:
            log(f'ERROR! {e} Are you sure you configured the IP Address correctly?')
        #Set the SO_REUSEADDR to allow immediate reuse of socket and set timeout for checking thread events
        discovery_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, ENABLE_SOCK_OPTION)
        discovery_socket.settimeout(SOCKET_RECIEVE_TIMEOUT)

        discovery_thread = threading.Thread(target=network_discovery_listener, args=[discovery_socket,])
        discovery_thread.start()

    #Initialize the tkinter moderation panel
    root = tkinter.Tk()
    root.title(TITLE)
    root.geometry(GEOMETRY)

    current_channel = tkinter.StringVar(root)
    last_update_time = tkinter.DoubleVar(root)

    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(0, weight=1)

    main_layout = tkinter.Frame(root)
    main_layout.grid_rowconfigure(0, weight=1)
    main_layout.grid_columnconfigure(0, weight=1)
    main_layout.grid_columnconfigure(1, weight=1)
    main_layout.grid_columnconfigure(2, weight=1)
    
    channel_select_frame = tkinter.Frame(main_layout)
    channel_select_frame.grid(row=0, column=0, sticky=tkinter.NSEW)

    channel_select_frame.grid_rowconfigure(1, weight=1)
    channel_select_frame.grid_columnconfigure(0, weight=1)

    channel_label = tkinter.Label(channel_select_frame, text='Channels')
    channel_label.grid(row=0, column=0)

    channel_select = tkinter.Listbox(channel_select_frame, width=20, height=14)
    channel_select.bind('<<ListboxSelect>>', on_channel_listbox_select)
    channel_select.grid(row=1, column=0, sticky=tkinter.NSEW)

    channel_y_scrollbar = tkinter.ttk.Scrollbar(channel_select_frame, orient=tkinter.VERTICAL,command=channel_select.yview)
    channel_select['yscrollcommand'] = channel_y_scrollbar.set
    channel_y_scrollbar.grid(row=1, column=1, sticky=tkinter.NS)

    channel_x_scrollbar = tkinter.ttk.Scrollbar(channel_select_frame, orient=tkinter.HORIZONTAL,command=channel_select.xview)
    channel_select['xscrollcommand'] = channel_x_scrollbar.set
    channel_x_scrollbar.grid(row=2, column=0, sticky=tkinter.EW)

    messages_frame = tkinter.Frame(main_layout)
    messages_frame.grid(row=0, column=1, sticky=tkinter.NSEW)

    messages_frame.grid_columnconfigure(0, weight=1)
    messages_frame.grid_rowconfigure(0, weight=1)

    messages_view = tkinter.Text(messages_frame, width=50, height=30, state=tkinter.DISABLED, wrap=tkinter.WORD)
    messages_view.grid(row=0, column=0, sticky=tkinter.NSEW)

    messages_view_scrollbar = tkinter.ttk.Scrollbar(messages_frame, orient=tkinter.VERTICAL, command=messages_view.yview)
    messages_view['yscrollcommand'] = messages_view_scrollbar.set
    messages_view_scrollbar.grid(row=0, column=1, sticky=tkinter.NS)

    user_list_frame = tkinter.Frame(main_layout)
    user_list_frame.grid(row=0, column=2, sticky=tkinter.NSEW)

    user_list_frame.grid_columnconfigure(0, weight=1)
    user_list_frame.grid_rowconfigure(1, weight=1)

    user_list_label = tkinter.ttk.Label(user_list_frame, text='Users in channel')
    user_list_label.grid(row=0, column=0)

    user_list = tkinter.Text(user_list_frame, width=20, height=30, state=tkinter.DISABLED)
    user_list.grid(row=1, column=0, sticky=tkinter.NSEW)

    user_list_scrollbar = tkinter.ttk.Scrollbar(user_list_frame, orient=tkinter.VERTICAL, command=user_list.yview)
    user_list['yscrollcommand'] = user_list_scrollbar.set
    user_list_scrollbar.grid(row=1, column=1, sticky=tkinter.NS)

    main_layout.grid(row=0, column=0, sticky=tkinter.NSEW)

    menubar = tkinter.Menu(main_layout)
    menubar_label = 'Options'

    general_menu = tkinter.Menu(menubar, tearoff=tkinter.FALSE)

    purge_submenu = tkinter.Menu(general_menu, tearoff=tkinter.FALSE)
    moderation_submenu = tkinter.Menu(general_menu, tearoff=tkinter.FALSE)

    general_menu.add_cascade(label='Purge...', menu=purge_submenu)

    purge_submenu.add_command(label='Unencrypted Clients', command=on_purge_unencrypted_menu_pressed)
    purge_submenu.add_command(label='Encrypted Clients', command=on_purge_encrypted_menu_pressed)

    general_menu.add_cascade(label='Moderation', menu=moderation_submenu)

    moderation_submenu.add_command(label='Ban User', command=on_ban_user_menu_pressed)
    moderation_submenu.add_command(label='Pardon User', command=on_pardon_user_menu_pressed)

    general_menu.add_separator()

    general_menu.add_command(label='Shutdown', command=on_server_shutdown_pressed)

    menubar.add_cascade(label=menubar_label, menu=general_menu)

    root.protocol("WM_DELETE_WINDOW", on_server_shutdown_pressed)
    root.config(menu=menubar)

    update_thread = threading.Thread(target=gui_update_handler)
    update_thread.start()

    root.mainloop()