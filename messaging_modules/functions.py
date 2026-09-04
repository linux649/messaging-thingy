'''
This program contains common functions for use with the messaging server and client.
'''
import json
import socket
import ssl
import uuid

from . import status

#validation functions
def is_port_valid(port: int):
    '''Checks whether an integer is a valid network port number.
    - num is the number to check.'''
    return status.MIN_PORT <= port <= status.MAX_PORT

def is_any_int_negative(num: list[int]):
    '''Checks whether any integer in a list is negative.
    - num is the list of numbers to check.'''
    for n in num:
        if n < 0:
            return True
    return False

def check_packet_initial_contents(packet: dict):
    '''Checks the contents of a message_server/message_client packet to make sure that it has the status and data fields.'''
    if status.PACKET_STATUS not in packet.keys() or status.PACKET_DATA not in packet.keys():
        return False
    return True

def check_uuid_valid(string: str, version:int=4):
    '''Checks if a string is a valid UUID version 4.'''
    try:
        uuid.UUID(string, version=version)
        return True
    except ValueError:
        return False

#network functions
def get_raw_buffer(conn: socket.socket, buffer_size: int=status.DEFAULT_BUFFER_SIZE):
    '''Gets input from a socket object buffer and splits and deserialises the packets into a list.
    - conn is a open socket object.
    - buffer_size is an int of the buffer to read out at a time. BEWARE! Setting this too high can cause increased memory consumption.'''
    buffer = ''
    while len(buffer) == 0 or buffer[-1] != status.END_PACKET: #keep adding the buffer into the buffer variable until an end of packet is reached.
        try:
            buffer += conn.recv(buffer_size).decode()
            if not buffer: #if the buffer contents are None, the connection closed, so quit out of the function, or risk a deadlock :P
                return None
        except TimeoutError:
            break
        except (ConnectionError, ssl.SSLError):
            return None
    #Parse the connection buffer
    result = parse_conn_buffer(buffer)

    return result

def parse_conn_buffer(buffer:str):
    '''Parses a message_server/message_client buffer string into a list.
    - buffer is a buffer string recieved from a connection.'''
    buffer_list = buffer.split(status.END_PACKET) #split the raw buffer into a list to parse individually

    parsed_packets = []
    for i in range(len(buffer_list)): #if the item has no contents, or cannot be deserialised from JSON, skip the packet, otherwise add to parsed packet list
        if buffer_list[i] == '':
            continue
        try:
            packet = json.loads(buffer_list[i])
            parsed_packets.append(packet)
        except json.JSONDecodeError:
            continue

    return parsed_packets

def send_conn_packet(conn: socket.socket, status_code: int, data='', addr:tuple=None):
    '''Sends a serialised packet to the connected peer.
    - conn is a open socket object.
    - status is a network status as an int.
    - data is a JSON serialisable datatype
    - addr is a tuple containing the address info (host,port) of the peer to send the packet to.'''
    #Serialise, add terminating character, and encode to send.
    packet = {status.PACKET_STATUS:status_code, status.PACKET_DATA:data}
    packet_json = json.dumps(packet) + status.END_PACKET
    try:
        if addr:
            conn.sendto(packet_json.encode(), addr)
        else:
            conn.sendall(packet_json.encode())
        return
    except ConnectionError as e:
        return e