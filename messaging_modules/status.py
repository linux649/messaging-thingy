'''
This Python module contains the constants for the server and client to use for:
- Network packet status information
- Network constant values
- Room types
'''
#network constant values
END_PACKET = '\x04'
PORT_ONE = 1
MIN_PORT = 1024
MAX_PORT = 65535
DEFAULT_SERVER_PORT= 38119
SERVER_DISCOVERY_PORT = 38121
CLIENT_DISCOVERY_PORT = 38122
DEFAULT_BUFFER_SIZE = 1024
LOCALHOST = '127.0.0.1'
BROADCAST = '255.255.255.255'
ALL_INTERFACES = '0.0.0.0'

#window values
START = 0
SPACE = '\u00a0'

# Reference: https://docs.tlsref.org/server-side-tls.html#intermediate-compatibility
CIPHERS = 'TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305'

#certificate constants
BEGIN_CERTIFICATE = '-----BEGIN CERTIFICATE-----'
END_CERTIFICATE = '-----END CERTIFICATE-----'

#packet constants
PACKET_STATUS = 'status'
PACKET_DATA = 'data'

DATA_PORT = 'tcp'
DATA_TLS = 'tls'
DATA_COMMON_NAME = 'cn'

DATA_TYPE = 'type'
DATA_ID = 'id'
DATA_MESSAGE = 'message'
DATA_DIRECTS = 'directs'
DATA_ROOMS = 'rooms'
DATA_USERNAME = 'username'
DATA_BANNED = 'banned'
DATA_FROM = 'from'
DATA_NAME = 'name'

USERNAME_MAX_LEN = 20

#room types
CHANNEL_TYPE_ROOM = 'room'
CHANNEL_TYPE_DIRECT = 'direct'

ROOM_NAME_MAX_LEN = 20

#network packet status constants

#network discovery
ATTEMPT_NET_DISCOVERY = 0
REPLY_NET_DISCOVERY = 1

#connecting to sockets
ATTEMPT_SERVER_JOIN = 2
SERVER_JOINED = 3

#unencrypted channel options
GET_SERVER_INFO = 4
REPLY_SERVER_INFO = 5

GET_TLS_CERT = 6
REPLY_TLS_CERT = 7

CLOSE_SOCKET = 8
SERVER_CLOSED_SOCKET = 9

#encrypted channel options
SET_USERNAME = 10

GET_USER_LIST = 13
REPLY_USER_LIST = 14

CREATE_DIRECT = 15

CREATE_ROOM = 17

GET_USER_INFO = 19
REPLY_USER_INFO = 20

JOIN_ROOM = 21

LEAVE_CHANNEL = 23

SEND_MESSAGE = 24

GET_MESSAGES = 25
REPLY_MESSAGES = 26

OPERATION_SUCCESS = 11
OPERATION_FAILURE = 12

#connection refusal
REFUSED_JOIN = 256
REFUSED_JOIN_FULL = 257

#connection issues due to moderation
REFUSED_CONN_BAN = 258
REFUSED_CONN_KICK = 259

#packet issues
BAD_REQUEST = 260