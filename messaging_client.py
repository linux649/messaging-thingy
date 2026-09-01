'''
This program is a messaging client allowing the user to connect to a messaging server
to communicate with other people over the local network.
'''
import configparser
import datetime
import errno
import hashlib
import os
import queue
import socket
import ssl
import threading
import time
import tkinter
import tkinter.ttk
import tkinter.messagebox
import tkinter.simpledialog
import uuid

#local library containing network status constants 
from messaging_modules import status, functions

#file constants
CLIENT_PROGRAM_DIR = os.path.dirname(os.path.abspath(__file__)) + os.path.sep
CLIENT_WORKING_DIR = CLIENT_PROGRAM_DIR  + '.client' + os.path.sep
CLIENT_CERT_DIR = CLIENT_WORKING_DIR  + 'certificates' + os.path.sep

#constants
CONFIG_FILENAME = 'client_config.ini'
SOCKET_RECIEVE_TIMEOUT = 3
SOCKET_BUFFER_COOLDOWN = 1
MAX_INFO_ATTEMPTS = 3
DISCOVERY_COOLDOWN = 2
CERTIFICATE_PUBLIC_EXT = '.crt'
WEEK_S = 7*24*60*60

DISPLAY_MAIN_MENU = 0
DISPLAY_CONNECT_MENU = 1
DISPLAY_CONNECTED = 2

REFRESH_INTERVAL = 2

MESSAGE_DATE_FORMAT = '%d/%m/%Y %H:%M'
MESSAGE_BOX_INITIAL_TEXT = '''Hello!

First time?
Go to options and create a room! 
Or create a direct message with someone else (make sure you have their UUID)!

Happy chatting :D!'''

HELP_MENU_TEXT = '''Hello and thanks for using this program!

Contents:
1. Connecting to a server
2. What can I do as a user?
3. What does it mean when it says I have been banned?

Appendix 1. Glossary

1. Connecting to a server

After clicking on the connect button, you are shown with three intimidating boxes, the discovery selector, the IP address entry, and the TCP port entry.
To be able to connect to a server, it either needs to be discoverable on the local network, or you need to know the server's IP address and TCP port.
To discover a server on the network, you can click the 'Search for servers' button and if any are found, you can autofill the server information by clicking on the server when discovered in the listbox!
If you aren't able to discover the server, or know the server's IP address and TCP port, you can fill this in yourself.

Note: The IP address entry accepts either a valid IPv4 address or hostname, and the TCP port entry accepts any TCP port in the valid range (1 - 65535).

2. What can I do as a user?

Once you are connected to a server, you can chat with others by selecting a channel (direct message or room) to chat with others in, in the designated listboxes.
If you aren't already in any channels, or want to join or make a new one, you can!
In the options menu, you can join rooms, or under New..., you can create a new direct message with another user, or make new room on the server!
To create a direct message with another user, you need to know what the other user's UUID is.
To join a room, you need to know what the room's UUID.
The requirement of needing to know the UUIDs to join rooms or create a direct message with someone else is to make sure that you generally know who the other person or what the room is somehow.
To leave a room or direct message with other user, you need to know what the UUID of the channel is. This is intended to ensure that the user is sure about leaving the channel.

3. What does it mean when it says I have been banned?

If you get a message that you have banned from the server while attempting to connect to it, this means that the server operator has banned you from chatting on their server.
You can't really do anything about this, since the server operator is the GOD of the server.
You can try to communicate with them by other means to understand why you have been banned or try to get them to pardon you, but a pardon is unlikely if they banned you deliberately.
A ban is permanent until the server operator pardons you.

Appendix 1. Glossary

local network - the local area network or LAN, is any network where your computer is connected directly to, like a wireless network, or a wired network, so they can communicate with other computers.
IP(v4) address - an IP address is an address that a computer uses to identify itself in a network. An IPv4 address has a format of xxx.xxx.xxx.xxx
TCP port - an interface that a computer uses to connect to other computers with the Transmission Control Protocol. There are 65535 of these ports, ranging from 1 to 65535. 
UUID - A Universally Uniquie IDentifier is a type of ID intended to guarantee uniqueness over time and space (from RFC 9562: https://datatracker.ietf.org/doc/html/rfc9562.html).
'''

#tkinter consts
TITLE = 'That Messaging Client!'
GEOMETRY = '800x510'
BIG_BUTTON_PADDING = 30
TITLE_LABEL_FONT = ("Segoi UI", 20)
TEXT_START = 1.0
CSS_LIGHTRED = '#FFCCCB'
CSS_RED = '#FF0000'
HOVER_RED = "#FF7D7D"

#global variables
display_mode = DISPLAY_MAIN_MENU
last_update_time = time.time() - WEEK_S
sent_sync = 0

#thread locks, queues, and events
current_room_lock = threading.RLock()
update_message_lock = threading.Lock()

socket_send_queue = queue.Queue()

close_encrypted_socket = threading.Event()
enable_live_refresh = threading.Event()
immediate_refresh = threading.Event()

#functions
def clear_text_info():
    '''Function that clears the contents of both the messages view and user list textboxes.'''
    messages_view.config(state=tkinter.NORMAL)
    messages_view.delete(1.0, tkinter.END)
    messages_view.config(state=tkinter.DISABLED)
    user_list.config(state=tkinter.NORMAL)
    user_list.delete(1.0, tkinter.END)
    user_list.config(state=tkinter.DISABLED)

def reset_message_display():
    '''Resets the last_update_time global variable to an hour before the current time and clears the message view for getting message history.'''
    global last_update_time
    last_update_time = time.time() - WEEK_S
    clear_text_info()
    immediate_refresh.set()

#file functions
def fix_missing_client_folders():
    '''Checks for critical folder structures and repairs them if missing.'''
    file_structure_title = 'File Structure'
    try:
        if not os.path.isdir(CLIENT_WORKING_DIR):
            tkinter.messagebox.showwarning(file_structure_title, f'{CLIENT_WORKING_DIR} is missing, repairing...')
            os.mkdir(CLIENT_WORKING_DIR)

        if not os.path.isdir(CLIENT_CERT_DIR):
            tkinter.messagebox.showwarning(file_structure_title, f'{CLIENT_CERT_DIR} is missing, repairing...')
            os.mkdir(CLIENT_CERT_DIR)

    except OSError as e:
        tkinter.messagebox.showerror(file_structure_title, f'File structure creation error! {e}')
        exit(errno.EPERM)

def write_new_config_file(config_file: str, id:str):
    '''Create a new configuration file for the client operation.
    - config_file should be a path like string
    - id should be a uuid.UUID'''
    config = configparser.ConfigParser()
    #set the configuration to write
    DEFAULT_CONFIG = {'ClientID':id}
    config['Client'] = DEFAULT_CONFIG
    tkinter.messagebox.showinfo('Configuration', 'Making a new configuration file...')
    with open(CONFIG_FILENAME, 'w') as config_file:
        config.write(config_file)

def read_config_file(config_file: str):
    '''Reads out the configuration file to configure the client operation.
    config_file should be a path like string'''
    config = configparser.ConfigParser()
    # set up default values in case of fallback needed due to no config file
    default_id = uuid.uuid4()
    DEFAULT_CONFIG = {'ClientID':default_id}
    config['Client'] = DEFAULT_CONFIG
    #loading in configuration overwrites the defaults set above, since most recent takes precedence
    if os.path.isfile(config_file):
        config.read(config_file)
    else:
        #if the config file is missing, create so client can identify
        write_new_config_file(config_file, default_id)
        
    configured_id = config['Client'].get('ClientID')
    if not functions.check_uuid_valid(configured_id):
        tkinter.messagebox.showwarning('Configuration', 'The saved UUID is not valid. A new UUID will be generated.')
        write_new_config_file(config_file, default_id)
        configured_id = default_id

    return configured_id

def get_certificate_list():
    '''This function returns a list of files with the .crt extenstion from the client certificate program.'''
    result = []
    for file in os.listdir(CLIENT_CERT_DIR):
        #file extensions should exist in the last 4 characters of a filename
        if CERTIFICATE_PUBLIC_EXT == file[-4:]:
            result.append(file[:-4])
    return result

def get_certificate(common_name):
    '''Reads the contents of a certificate file.'''
    if common_name not in get_certificate_list():
        return
    #return if there is an issue reading the file (FileNotFoundError, PermissionError has a base class of OSError)
    try:
        with open(CLIENT_CERT_DIR+common_name+CERTIFICATE_PUBLIC_EXT) as certfile:
            contents = certfile.read()
            return contents
    except OSError:
        return

def save_certificate(common_name, cert_contents):
    '''Saves a certificate to the client certificate directory.'''
    with open(CLIENT_CERT_DIR+common_name+CERTIFICATE_PUBLIC_EXT, 'w') as certfile:
        certfile.write(cert_contents)

#socket functions
def prepare_encrypted_connection(host, tcp_port):
    '''Gets information from the server to prepare the encrypted connection with the unencrypted server port.
    - host is the server's IP address
    - tcp_port is the server's unencrypted TCP port'''
    #initialise variables
    certificate = None
    common_name = None
    tls_port = None
    #count attempts, if number of attempts go over MAX_INFO_ATTEMPTS, the server might be timing out or unreachable
    attempt = 0
    while attempt <= MAX_INFO_ATTEMPTS and (not certificate or not common_name or not tls_port):
        attempt += 1
        try:
            sock = socket.create_connection((host, tcp_port), SOCKET_RECIEVE_TIMEOUT)
        # socket.gaierror and ConnectionError both have a base class of OSError
        except (OSError, OverflowError):
            return
        functions.send_conn_packet(sock, status.ATTEMPT_SERVER_JOIN)
        buffer = functions.get_raw_buffer(sock)
        if not buffer:
            continue
        #get the first packet
        packet = buffer[0]
        buffer.pop(0)
        if not functions.check_packet_initial_contents(packet) or packet[status.PACKET_STATUS] != status.SERVER_JOINED:
            sock.close()
            continue
        #if tls_port or common_name missing, GET_SERVER_INFO and if certificate missing, GET_TLS_CERT
        if not common_name and not tls_port:
            functions.send_conn_packet(sock, status.GET_SERVER_INFO)
        if not certificate:
            functions.send_conn_packet(sock, status.GET_TLS_CERT)
        #wait some period of time to make sure that no packets are skipped and the loop is processed again for no reason
        time.sleep(SOCKET_BUFFER_COOLDOWN)
        buffer = functions.get_raw_buffer(sock)
        #something weird has happened if the buffer is None or empty
        if not buffer:
            continue
        #check the buffer packets
        for packet in buffer:
            #check the validity and the status of the packets to match to data
            if not functions.check_packet_initial_contents(packet):
                continue
            match packet[status.PACKET_STATUS]:
                case status.REPLY_SERVER_INFO:
                    try:
                        tls_port = packet[status.PACKET_DATA][status.DATA_TLS]
                        common_name = packet[status.PACKET_DATA][status.DATA_COMMON_NAME]
                    except KeyError:
                        continue
                case status.REPLY_TLS_CERT:
                    #BEGIN_CERTIFICATE and END_CERTIFICATE must exist in a TLS certificate
                    if status.BEGIN_CERTIFICATE in packet[status.PACKET_DATA] and status.END_CERTIFICATE in packet[status.PACKET_DATA]:
                        certificate = packet[status.PACKET_DATA]
        #gracefully close the socket after an attempt
        functions.send_conn_packet(sock, status.CLOSE_SOCKET)
        sock.close()
    #check that the data is there and valid
    data = (certificate, common_name, tls_port)
    if all(data):
        return data
    else:
        return

def encrypted_socket_handler(conn:ssl.SSLSocket, id:uuid.UUID):
    '''Function that handles the encrypted socket communication from this client to the server.
    - conn should be a ssl.SSLSocket
    - addr should be a tuple that contains the address information e.g. (host, port)'''
    global last_update_time
    #initialise variables for tkinter.messagebox use
    messagebox_title = 'Connection'
    functions.send_conn_packet(conn, status.ATTEMPT_SERVER_JOIN, {status.DATA_ID:id})
    buffer = functions.get_raw_buffer(conn)
    if not buffer:
        messagebox_contents = 'Connection issue with server!'
        tkinter.messagebox.showerror(messagebox_title, messagebox_contents)
        cycle_display_mode()
        return
    packet = buffer[0]
    buffer.pop(0)
    if not functions.check_packet_initial_contents(packet) or (packet[status.PACKET_STATUS] not in (status.SERVER_JOINED, status.REFUSED_JOIN)):
        messagebox_contents = 'The server sent an invalid packet.'
        tkinter.messagebox.showerror(messagebox_title, messagebox_contents)
        cycle_display_mode()
        return
    elif packet[status.PACKET_STATUS] == status.REFUSED_JOIN:
        messagebox_contents = 'You have been banned from the server.'
        tkinter.messagebox.showerror(messagebox_title, messagebox_contents)
        cycle_display_mode()
        return

    enable_live_refresh.set()
    update_thread = threading.Thread(target=refresh_messages)
    update_thread.start()

    try:
        while not close_encrypted_socket.is_set():
            #queue.empty() method is not reliable?, so if get_nowait produces empty error, break out
            while not socket_send_queue.empty():
                try:
                    #send packets if needed
                    p_status, p_data = socket_send_queue.get_nowait()
                    functions.send_conn_packet(conn, p_status, p_data)
                except queue.Empty:
                    break
            #gets data from the socket buffer to repopulate the buffer list if empty
            if len(buffer) == 0:
                recieved_packets = functions.get_raw_buffer(conn)
                
                if recieved_packets == None: # returned by get_raw_buffer and parse_conn_buffer when there is a connection issue
                    messagebox_contents = 'There is a connection issue with the server.'
                    tkinter.messagebox.showerror(messagebox_title, messagebox_contents)
                    break
                
                for packet in recieved_packets:
                    buffer.append(packet)

            if len(buffer) == 0: #if the buffer is still empty after getting the packets from the socket buffer, try again
                continue

            #Get the first packet from the buffer
            packet = buffer[0]
            buffer.pop(0)

            if not functions.check_packet_initial_contents(packet):
                functions.send_conn_packet(conn, status.BAD_REQUEST)
                continue

            packet_status = packet[status.PACKET_STATUS]

            match packet_status:
                case status.OPERATION_SUCCESS:
                    tkinter.messagebox.showinfo('Operation', 'The operation was successful!')
                case status.OPERATION_FAILURE:
                    data = packet[status.PACKET_DATA]
                    tkinter.messagebox.showerror('Operation', f'The operation failed! ({data})')
                case status.REPLY_USER_INFO:
                    direct_messages = packet[status.PACKET_DATA][status.DATA_DIRECTS]
                    rooms = packet[status.PACKET_DATA][status.DATA_ROOMS]
                    direct_channel_select.delete(status.START, tkinter.END)
                    room_channel_select.delete(status.START, tkinter.END)
                    for direct, info in direct_messages.items():
                        other_id = other_name = '(none)' #if no other user is associated with the direct message, they probably left it
                        if info:
                            other_id, other_name = info
                    #in the following, \u00a0 is used so the change_to<room_type> events can read the channel id, without having to rely on an extra list.
                        direct_channel_select.insert(tkinter.END, f'{other_name} ({other_id}){status.SPACE}{direct}')
                    for room_id, name in rooms.items():
                        room_channel_select.insert(tkinter.END, name + status.SPACE + room_id)
                case status.REPLY_USER_LIST:
                    users = packet[status.PACKET_DATA]
                    result = ''
                    current = user_list.get(1.0, tkinter.END)
                    for user_id, username in users.items():
                        result += f'{username} ({user_id})\n' #form the would-be result
                    if current.strip() != result.strip(): #only change the user_list textbox if there is differences
                        user_list.config(state=tkinter.NORMAL)
                        user_list.delete(1.0, tkinter.END)
                        user_list.insert(tkinter.END, result)
                        user_list.config(state=tkinter.DISABLED)
                case status.REPLY_MESSAGES:
                    with update_message_lock:
                        #get the latest message time from server packet
                        last_message_time = float(packet[status.PACKET_DATA][status.DATA_FROM])
                        channel_type = packet[status.PACKET_DATA][status.DATA_TYPE]
                        channel_id = packet[status.PACKET_DATA][status.DATA_ID]
                        print(last_message_time, last_update_time)
                        can_acquire = current_room_lock.acquire(False)
                        if not can_acquire:
                            continue
                        else:
                            current_type, current_id = current_room.get().split(status.SPACE, maxsplit=1)
                            if current_type != channel_type or current_id != channel_id:
                                current_room_lock.release()
                                continue
                            
                            if last_message_time > last_update_time: #if it is greater than the client saved last_update_time, update and display
                                last_update_time = last_message_time
                                messages = packet[status.PACKET_DATA][status.DATA_MESSAGE]
                                messages_view.config(state=tkinter.NORMAL)
                                for time, message in messages.items():
                                    formatted_time = datetime.datetime.fromtimestamp(float(time)).strftime(MESSAGE_DATE_FORMAT)
                                    messages_view.insert(tkinter.END, f'[{formatted_time}] {message}\n')
                                    root.update()
                                messages_view.config(state=tkinter.DISABLED)
                            current_room_lock.release()
                case status.SERVER_CLOSED_SOCKET:
                    tkinter.messagebox.showerror(messagebox_title, 'The server has closed the connection.')
                    break
                case _:
                    functions.send_conn_packet(conn, status.BAD_REQUEST)
                    continue
        conn.close()
        close_encrypted_socket.clear()
        enable_live_refresh.clear()
        back_to_main_menu()
    except RuntimeError: #tkinter window functions will break out with RuntimeError when the window on the main thread is closed
        return


def initialise_encrypted_connection(common_name:str, host:str, tls_port:int):
    '''Creates the connection object and starts the listener thread.
    - common_name should be the common name of the certificate that the server gives.
    - host should be a valid IPv4 address or hostname
    - tls_port should be a TCP port that is for TLS given by the server.'''
    #configure the connection and the TLS context
    address_info = (host, tls_port)
    encrypted_conn = socket.create_connection(address_info, SOCKET_RECIEVE_TIMEOUT)
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers(status.CIPHERS)
    #attempt to load the certificate, and return if unable
    try:
        context.load_verify_locations(CLIENT_CERT_DIR+common_name+CERTIFICATE_PUBLIC_EXT)
    except FileNotFoundError:
        tkinter.messagebox.showerror('The client could not find the certificate file, please try again.')
        return
    except ssl.SSLError:
        tkinter.messagebox.showerror('The format of the saved certificate seems to be invalid, please try again.')
        return
    wrapped_socket = context.wrap_socket(encrypted_conn, server_hostname=common_name)
    handler_thread = threading.Thread(target=encrypted_socket_handler, args=[wrapped_socket, USER_ID])
    handler_thread.start()
    cycle_display_mode()
    
    

def network_discover_servers():
    '''Sends a network discovery packet to the universal broadcast address (255.255.255.255) to attempt to discover messaging servers.'''
    # Disable the button component, so no new threads can be spawned
    search_for_servers_button.config(text="Searching...", state=tkinter.DISABLED)
    # Clear the listbox
    discovery_server_select.delete(0, tkinter.END)
    # Setup the discovery socket
    discovery_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    discovery_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    discovery_socket.bind((status.ALL_INTERFACES, status.CLIENT_DISCOVERY_PORT))
    discovery_socket.settimeout(DISCOVERY_COOLDOWN)
    # Send a discovery attempt, and wait some time for the packets to pool in the buffer.
    functions.send_conn_packet(discovery_socket, status.ATTEMPT_NET_DISCOVERY, addr=(status.BROADCAST, status.SERVER_DISCOVERY_PORT))
    #Initialise check variables
    buffer = {}
    raw_buffer = True
    while raw_buffer:
        #recieve packets from the buffer until there is no more packets (timeout)
        try:
            raw_buffer, addr = discovery_socket.recvfrom(1024)
        except TimeoutError:
            break
        #add the packets into the buffer dict for processing
        raw_buffer = raw_buffer.decode()
        parsed_buffer = functions.parse_conn_buffer(raw_buffer)
        for packet in parsed_buffer:
            buffer.update({addr[0]:packet})
    if buffer:
        #check the packets for validity and add them to the listbox if so
        for addr, packet in buffer.items():
            port = packet[status.PACKET_DATA][status.DATA_PORT]
            common_name = packet[status.PACKET_DATA][status.DATA_COMMON_NAME]
            try:
                if functions.check_packet_initial_contents(packet) and port and common_name:
                    discovery_server_select.insert(tkinter.END, f"{addr}:{port} {common_name}")
                    root.update()
            except KeyError:
                continue
    search_for_servers_button.config(text="Search for servers...", state=tkinter.NORMAL)

#tkinter validatecommands
def message_entry_limit(P):
    '''Tkinter validation command that makes sure that the length of the message entry contents is not more than 100 characters.'''
    return len(P) < 100

def check_valid_tcp_port(P):
    '''Tkinter validation command that makes sure that the entered TCP port is valid and a number.'''
    if str.isdigit(P):
        return int(P) <= status.MAX_PORT and int(P) >= status.PORT_ONE
    else:
        return P == ''

#window events
def on_close():
    '''This function handles the closing of the root window.'''
    result = tkinter.messagebox.askyesnocancel('Disconnect', 'Are you sure you want to disconnect and close the client?')
    if not result:
        return
    close_encrypted_socket.set()
    enable_live_refresh.clear()
    root.destroy()

def on_disconnect():
    '''Sets the close_encrypted_socket thread to signal the encrypted socket thread to close.'''
    close_encrypted_socket.set()
    back_to_main_menu()

def clear_gui():
    '''This function unrenders all of the GUI components of all of the display layouts.'''
    main_menu.grid_forget()
    connect_menu.grid_forget()
    connected_layout.grid_forget()

def back_to_main_menu():
    '''This function clears the currently rendered GUI and resets it to the Main Menu display mode.'''
    global display_mode
    clear_gui()
    main_menu.grid(row=0, column=0, sticky=tkinter.NSEW)
    main_menu.grid_columnconfigure(0, weight=1)
    main_menu.grid_columnconfigure(2, weight=1)
    main_menu.grid_rowconfigure(1, weight=1)
    main_menu.grid_rowconfigure(3, weight=1)
    menubar.entryconfig(menubar_label, state=tkinter.DISABLED)
    current_room.set('')
    display_mode = DISPLAY_MAIN_MENU #need to unset enable live refresh in v2

def cycle_display_mode():
    '''This function cycles through the display modes when a button with the command set to this function is clicked.'''
    global display_mode
    clear_gui()
    # Cycle: Main Menu --> Connect Menu --> Connected Layout/Messaging Client --> Repeat
    if display_mode == DISPLAY_MAIN_MENU:
        connect_menu.grid(row=0, column=0, sticky=tkinter.NSEW)
        connect_menu.grid_columnconfigure(1, weight=1)
        connect_menu.grid_rowconfigure(0, weight=1)
        connect_menu.grid_rowconfigure(1, weight=1)
        display_mode = DISPLAY_CONNECT_MENU
    elif display_mode == DISPLAY_CONNECT_MENU:
        connected_layout.grid(row=0, column=0, sticky=tkinter.NSEW)
        connected_layout.grid_rowconfigure(0, weight=1)
        connected_layout.grid_columnconfigure(0, weight=1)
        connected_layout.grid_columnconfigure(1, weight=1)
        connected_layout.grid_columnconfigure(2, weight=1)
        menubar.entryconfig(menubar_label, state=tkinter.NORMAL)
        messages_view.delete(TEXT_START, tkinter.END)
        user_list.delete(TEXT_START, tkinter.END)
        display_mode = DISPLAY_CONNECTED
    elif display_mode == DISPLAY_CONNECTED:
        back_to_main_menu()
    
def on_discover_servers_button_pressed():
    '''This function makes a thread for network discovery when the search button is pressed, so the main window can still be used.'''
    thread = threading.Thread(target=network_discover_servers)
    thread.start()

def on_connect_listbox_select(*event):
    '''Tkinter event that triggers when an item in the connect menu listbox is selected.'''
    #get the selection and split it up to relevant info
    try:
        selection = discovery_server_select.selection_get()
        ip_info = selection.split(maxsplit=1)[0]
        ip_addr, tcp_port = ip_info.split(':')

        #clear and set the values based on the selection
        ip_addr_entry.delete(status.START, tkinter.END)
        ip_addr_entry.insert(status.START, ip_addr)

        tcp_port_entry.delete(status.START, tkinter.END)
        tcp_port_entry.insert(status.START, tcp_port)
    except tkinter.TclError:
        return

def reset_connect_button(message: str | None=None):
    '''Function that runs when another function wants to reset the connect menu's connect button, optionally with a
       tkinter.messagebox.showerror
    - message should be a message string that would be the contents of a tkinter.messagebox.showerror'''
    if message:
        messagebox_title = 'Connect'
        tkinter.messagebox.showerror(messagebox_title, message)
    connect_button.config(state=tkinter.NORMAL)


def on_connect_button_pressed():
    '''Tkinter event that triggers when the connect menu's connect button is pressed.'''
    #force disable the button to make sure that new threads cannot be made until the button is enabled again.
    connect_button.config(state=tkinter.DISABLED)
    root.update()

    messagebox_title = 'Connect'
    #get the information and wait for the function to get the info from the server.
    ip_addr = ip_address_var.get()
    tcp_port = tcp_port_var.get()
    result = prepare_encrypted_connection(ip_addr, tcp_port)
    #the function returns None if the operation is unsuccessful
    if not result:
        messagebox_contents = 'The connection could not be prepared. Make sure that the connection information is correct!'
        reset_connect_button(messagebox_contents)
        return
    #parse the information returned from the preparation function
    certificate, common_name, tls_port = result
    #check certificates if they exist to see if they match, otherwise save it
    new_cert_hash = hashlib.sha256(certificate.encode()).hexdigest()
    existing_certs = get_certificate_list()
    if common_name in existing_certs:
        existing_cert = get_certificate(common_name)
        if existing_cert:
            old_cert_hash = hashlib.sha256(existing_cert.encode()).hexdigest()
            #if the old certificate and new certificate don't match, alert the user to ensure
            #that the certificates match, because the change could be due to server configuration or MITM attacks.
            if new_cert_hash != old_cert_hash:
                messagebox_contents = f'The server has sent a different certificate. Overwrite current certificate?\nOld: {old_cert_hash}\nNew: {new_cert_hash}'
                result = tkinter.messagebox.askyesno(messagebox_title, messagebox_contents)
                if result:
                    save_certificate(common_name, certificate)
                else:
                    messagebox_contents = 'The connection has been aborted due to a certificate difference.'
                    reset_connect_button(messagebox_contents)
                    return
        else:
            messagebox_contents = 'An error occured while attempting to read out the saved certificate.'
            reset_connect_button(messagebox_contents)
            return
    else:
        messagebox_contents = f'New certificate has been saved.\nHash: {new_cert_hash}'
        tkinter.messagebox.showinfo(messagebox_title, messagebox_contents)
        save_certificate(common_name, certificate)
    #move on to the connected display mode
    initialise_encrypted_connection(common_name, ip_addr, tls_port)
    reset_connect_button()

def on_send_message_event(*event):
    '''Tkinter function that is bound to the send button and pressing Enter/Return in the message entry.
    - *event is the tkinter event information.'''
    if current_room:
        with current_room_lock:
            channel_type, channel_id = current_room.get().split(status.SPACE)
            message = messages_entry.get()
            print(message)
            queue_data = (status.SEND_MESSAGE, {status.DATA_TYPE:channel_type, status.DATA_ID:channel_id, status.DATA_MESSAGE:message})
            socket_send_queue.put(queue_data)
            messages_entry.delete(status.START, tkinter.END)

def change_to_direct(*event):
    '''This function is bound to the tkinter event that activates when an item in the direct message listbox is selected.'''
    try: #_tkinter.TclError is raised when the client hasn't yet recieved the info from the server yet
        selection = direct_channel_select.selection_get()
        name, direct_id = selection.split(status.SPACE, maxsplit=1)
        direct_channel_select.selection_clear(status.START, tkinter.END)
    except (tkinter.TclError, IndexError):
        return
    if functions.check_uuid_valid(direct_id):
        can_acquire = current_room_lock.acquire(blocking=False)
        if can_acquire:
            current_room.set(status.CHANNEL_TYPE_DIRECT+status.SPACE+direct_id)
            display_current.set(f'{name} ({direct_id})')
            reset_message_display()
            current_room_lock.release()

def change_to_room(*event):
    '''This function is bound to the tkinter event that activates when an item in the room listbox is selected.'''
    try:#_tkinter.TclError is raised when the client hasn't yet recieved the info from the server yet
        selection = room_channel_select.selection_get()
        name, room_id = selection.split(status.SPACE,maxsplit=1)
        room_channel_select.selection_clear(status.START, tkinter.END)
    except (tkinter.TclError, IndexError, ValueError):
        return
    if functions.check_uuid_valid(room_id):
        can_acquire = current_room_lock.acquire(blocking=False)
        if can_acquire:
            current_room.set(status.CHANNEL_TYPE_ROOM+status.SPACE+room_id)
            display_current.set(f'{name} ({room_id})')
            reset_message_display()
            current_room_lock.release()

def refresh_messages():
    '''Event handler that activates at a set interval that sends a message to refresh the messages, user lists, and user info.'''
    while enable_live_refresh.is_set():
        immediate_refresh.clear()
        socket_send_queue.put((status.GET_USER_INFO, ''))
        can_acquire = current_room_lock.acquire(blocking=False)
        if can_acquire:
            if current_room.get():
                channel_type, channel_id = current_room.get().split(status.SPACE)
                print(channel_type, channel_id)
                socket_send_queue.put((status.GET_USER_LIST, {status.DATA_TYPE:channel_type, status.DATA_ID:channel_id}))
                socket_send_queue.put((status.GET_MESSAGES, {status.DATA_TYPE:channel_type, status.DATA_ID:channel_id, status.DATA_FROM:last_update_time}))
            current_room_lock.release()
        immediate_refresh.wait(REFRESH_INTERVAL)

def on_create_room():
    '''Tkinter event bound to when the room option in the create submenu is pressed.'''
    name = tkinter.simpledialog.askstring('New Room', 'Enter a name for the new room: ')
    if not name:
        return
    socket_send_queue.put((status.CREATE_ROOM, {status.DATA_NAME: name}))

def on_create_direct():
    '''Tkinter event bound to when the direct option in the create submenu is pressed.'''
    other_uuid = tkinter.simpledialog.askstring('New Direct Message', 'Enter the other user\'s UUID: ')
    if not other_uuid:
        return
    socket_send_queue.put((status.CREATE_DIRECT, {status.DATA_ID: other_uuid}))

def on_join_room():
    '''Tkinter event bound to when the join room option in the menu is pressed.'''
    room_id = tkinter.simpledialog.askstring('Join Room', 'Enter the UUID of the room you want to join:')
    if not room_id:
        return
    socket_send_queue.put((status.JOIN_ROOM, {status.DATA_ID:room_id}))

def on_leave_room():
    '''Tkinter event bound to when the room option in the leave submenu in the menu is pressed.'''
    room_id = tkinter.simpledialog.askstring('Leave Room', 'Enter the UUID of the room you want to leave:')
    if not room_id:
        return
    socket_send_queue.put((status.LEAVE_CHANNEL, {status.DATA_TYPE:status.CHANNEL_TYPE_ROOM, status.DATA_ID:room_id}))

def on_leave_direct():
    '''Tkinter event bound to when the direct option in the leave submenu in the menu is pressed.'''
    direct_id = tkinter.simpledialog.askstring('Leave Direct Message', 'Enter the UUID of the direct message you want to leave:')
    if not direct_id:
        return
    socket_send_queue.put((status.LEAVE_CHANNEL, {status.DATA_TYPE:status.CHANNEL_TYPE_DIRECT, status.DATA_ID:direct_id}))

def on_set_username():
    '''Tkinter event bound to when the set username option is selected in the menu.'''
    username = tkinter.simpledialog.askstring('Set Username', 'Enter your new username: (long usernames will be shortened)')
    if not username:
        return
    elif len(username) > status.USERNAME_MAX_LEN:
        username = username[:status.USERNAME_MAX_LEN]
    socket_send_queue.put((status.SET_USERNAME, {status.DATA_USERNAME:username}))

def on_exit_entered(*event):
    '''Tkinter event bound to when the exit button in the main menu is hovered over.
    - *event is the tkinter event information.'''
    menu_exit_button.configure(bg=HOVER_RED)

def on_exit_leave(*event):
    '''Tkinter event bound to when the exit button in the main menu is no longer hovered over.
    - *event is the tkinter event information.'''
    menu_exit_button.configure(bg=CSS_LIGHTRED)

def on_help_menu_pressed(*event):
    '''Tkinter event bound to help menu button pressed.
    - *event is the tkinter event information.'''
    help_menu = tkinter.Tk()
    help_menu.title(TITLE)
    help_menu.geometry(GEOMETRY)

    help_menu.grid_rowconfigure(0, weight=1)
    help_menu.grid_columnconfigure(0, weight=1)

    main_text = tkinter.Text(help_menu, wrap='word')
    main_text.insert(tkinter.END, HELP_MENU_TEXT)
    main_text.configure(state=tkinter.DISABLED)
    main_text.grid(row=0, column=0, sticky=tkinter.NSEW)

    scrollbar = tkinter.ttk.Scrollbar(help_menu, orient=tkinter.VERTICAL, command=main_text.yview)
    main_text['yscrollcommand'] = scrollbar.set
    scrollbar.grid(row=0, column=1, sticky=tkinter.NS)

    help_menu.mainloop()

def on_copy_user_menu_pressed():
    '''Tkinter event bound to when the copy > user UUID menu button is pressed.'''
    root.clipboard_clear()
    root.clipboard_append(USER_ID)
    tkinter.messagebox.showinfo('Copy', 'Copied user UUID to the clipboard!')

def on_copy_channel_pressed():
    '''Tkinter event bound to when the copy > channel UUID menu button is pressed.'''
    if current_room.get():
        channel_type, channel_id = current_room.get().split(status.SPACE, maxsplit=1)
        if channel_type:
            root.clipboard_clear()
            root.clipboard_append(channel_id)
            tkinter.messagebox.showinfo('Copy', 'Copied channel UUID to the clipboard!')
            return
    #otherwise:
    tkinter.messagebox.showerror('Copy', 'Not currently in a channel!')

if __name__ == '__main__':
    #make sure that the program is running in the program's current folder
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    #fix any missing folders
    fix_missing_client_folders()
    #read out config file
    USER_ID = read_config_file(CONFIG_FILENAME)
    ##################
    # GUI Components #
    ##################
    # root window setup
    root = tkinter.Tk()
    root.title(TITLE)
    root.geometry(GEOMETRY)

    current_room = tkinter.StringVar(root)
    display_current = tkinter.StringVar(root)

    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(0, weight=1)

    #tkinter variables
    ip_address_var = tkinter.StringVar(root)
    tcp_port_var = tkinter.IntVar(root, value=status.DEFAULT_SERVER_PORT)

    #main menu
    main_menu = tkinter.Frame(root)
    main_menu.grid(row=0, column=0, sticky=tkinter.NSEW)

    main_menu.grid_columnconfigure(0, weight=1)
    main_menu.grid_columnconfigure(2, weight=1)
    main_menu.grid_rowconfigure(1, weight=1)
    main_menu.grid_rowconfigure(3, weight=1)

    title_label = tkinter.Label(main_menu, text=TITLE, font=TITLE_LABEL_FONT)
    title_label.grid(row=0, column=1)

    go_to_connect_button = tkinter.ttk.Button(main_menu, text='Connect to a server...', padding=BIG_BUTTON_PADDING, command=cycle_display_mode)
    go_to_connect_button.grid(row=2, column=1)

    menu_exit_button = tkinter.Button(main_menu, text='Exit', command=on_close, bg=CSS_LIGHTRED, activebackground=CSS_RED, relief=tkinter.GROOVE, width=10, border=1)
    menu_exit_button.bind('<Enter>', on_exit_entered)
    menu_exit_button.bind('<Leave>', on_exit_leave)
    menu_exit_button.grid(row=4, column=1)

    #connect menu
    connect_menu = tkinter.Frame(root)

    #network discovery section
    network_discovery_frame = tkinter.Frame(connect_menu)
    network_discovery_frame.grid(row=0, column=1, columnspan=2)

    network_discovery_label = tkinter.Label(network_discovery_frame, text='Network Discovery')
    network_discovery_label.grid(row=0, column=0)

    discovery_server_select = tkinter.Listbox(network_discovery_frame, width=50, height=20, selectmode=tkinter.SINGLE)
    discovery_server_select.grid(row=1, column=0, rowspan=5)
    discovery_server_select.bind('<<ListboxSelect>>', on_connect_listbox_select)

    discovery_select_scrollbar = tkinter.Scrollbar(network_discovery_frame, orient=tkinter.VERTICAL,command=discovery_server_select.yview)
    discovery_server_select['yscrollcommand'] = discovery_select_scrollbar.set
    discovery_select_scrollbar.grid(row=1, column=1, sticky=tkinter.NS, rowspan=5)

    search_for_servers_button = tkinter.ttk.Button(network_discovery_frame, text="Search for servers...", command=on_discover_servers_button_pressed)
    search_for_servers_button.grid(row=1, column=3)

    #connect information section
    connect_info_frame = tkinter.Frame(connect_menu)
    connect_info_frame.grid(row=1, column=1)

    connect_info_label = tkinter.Label(connect_info_frame, text='Connect')
    connect_info_label.grid(row=0, column=0)

    ip_addr_frame = tkinter.Frame(connect_info_frame)
    ip_addr_frame.grid(row=1, column=0)

    ip_addr_label = tkinter.Label(ip_addr_frame, text='IP Address or Hostname:')
    ip_addr_label.grid(row=0, column=0)

    ip_addr_entry = tkinter.ttk.Entry(ip_addr_frame, textvariable=ip_address_var, width=30)
    ip_addr_entry.grid(row=0, column=1)

    tcp_port_frame = tkinter.Frame(connect_info_frame)
    tcp_port_frame.grid(row=2, column=0)

    port_validate_command = (tcp_port_frame.register(check_valid_tcp_port))

    tcp_port_label = tkinter.Label(tcp_port_frame, text='TCP Port:')
    tcp_port_label.grid(row=0, column=0)

    tcp_port_entry = tkinter.ttk.Entry(tcp_port_frame, textvariable=tcp_port_var, width=30, validate=tkinter.ALL, validatecommand=(port_validate_command, '%P'))
    tcp_port_entry.grid(row=0, column=1)

    connect_button = tkinter.ttk.Button(connect_menu, text='Connect', command=on_connect_button_pressed)
    connect_button.grid(row=3, column=1)

    back_to_menu_button = tkinter.ttk.Button(connect_menu, text='Back to Menu', command=back_to_main_menu)
    back_to_menu_button.grid(row=4, column=0, sticky=tkinter.SW)
    #connected layout
    connected_layout = tkinter.Frame(root)

    channel_select_frame = tkinter.Frame(connected_layout)
    channel_select_frame.grid(row=0, column=0, sticky=tkinter.NSEW)

    channel_select_frame.grid_rowconfigure(1, weight=1)
    channel_select_frame.grid_rowconfigure(3, weight=1)
    channel_select_frame.grid_columnconfigure(0, weight=1)

    direct_channel_label = tkinter.ttk.Label(channel_select_frame, text='Direct Messages')
    direct_channel_label.grid(row=0, column=0)

    direct_channel_select = tkinter.Listbox(channel_select_frame, width=20, height=14)
    direct_channel_select.bind('<<ListboxSelect>>', change_to_direct)
    direct_channel_select.grid(row=1, column=0, sticky=tkinter.NSEW)

    direct_channel_scrollbar = tkinter.ttk.Scrollbar(channel_select_frame, orient=tkinter.VERTICAL,command=direct_channel_select.yview)
    direct_channel_select['yscrollcommand'] = direct_channel_scrollbar.set
    direct_channel_scrollbar.grid(row=1, column=1, sticky=tkinter.NS)

    room_channel_label = tkinter.ttk.Label(channel_select_frame, text='Rooms')
    room_channel_label.grid(row=2, column=0)

    room_channel_select = tkinter.Listbox(channel_select_frame, width=20, height=14)
    room_channel_select.bind('<<ListboxSelect>>', change_to_room)
    room_channel_select.grid(row=3, column=0, sticky=tkinter.NSEW)

    room_channel_scrollbar = tkinter.ttk.Scrollbar(channel_select_frame, orient=tkinter.VERTICAL,command=room_channel_select.yview)
    room_channel_select['yscrollcommand'] = room_channel_scrollbar.set
    room_channel_scrollbar.grid(row=3, column=1, sticky=tkinter.NS)

    messages_frame = tkinter.Frame(connected_layout)
    messages_frame.grid(row=0, column=1, sticky=tkinter.NSEW)

    messages_frame.grid_columnconfigure(0, weight=1)
    messages_frame.grid_rowconfigure(1, weight=1)

    messages_view_label = tkinter.Label(messages_frame, textvariable=display_current)
    messages_view_label.grid(row=0, column=0)

    messages_view = tkinter.Text(messages_frame, width=50, height=30, wrap=tkinter.WORD)
    messages_view.insert(tkinter.END, MESSAGE_BOX_INITIAL_TEXT)
    messages_view.configure(state=tkinter.DISABLED)
    messages_view.grid(row=1, column=0, sticky=tkinter.NSEW)

    messages_view_scrollbar = tkinter.ttk.Scrollbar(messages_frame, orient=tkinter.VERTICAL, command=messages_view.yview)
    messages_view['yscrollcommand'] = messages_view_scrollbar.set
    messages_view_scrollbar.grid(row=1, column=1, sticky=tkinter.NS)

    message_entry_frame = tkinter.Frame(messages_frame)
    message_entry_frame.grid(row=2, column=0, rowspan=2, sticky=tkinter.EW)

    message_entry_frame.grid_columnconfigure(0, weight=1)

    message_validate_command = (messages_frame.register(message_entry_limit))

    messages_entry = tkinter.ttk.Entry(message_entry_frame, width=55, validate=tkinter.ALL, validatecommand=(message_validate_command, '%P'))
    messages_entry.bind('<Return>', on_send_message_event)
    messages_entry.grid(row=0, column=0, sticky=tkinter.EW)

    send_button = tkinter.ttk.Button(message_entry_frame, text='Send', command=on_send_message_event)
    send_button.grid(row=0, column=1)

    user_list_frame = tkinter.Frame(connected_layout)
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

    menubar = tkinter.Menu(connected_layout)
    menubar_label = 'Options'

    general_menu = tkinter.Menu(menubar, tearoff=tkinter.FALSE)
    copy_menu = tkinter.Menu(menubar, tearoff=tkinter.FALSE)
    new_submenu = tkinter.Menu(general_menu, tearoff=tkinter.FALSE)
    leave_menu = tkinter.Menu(general_menu, tearoff=tkinter.FALSE)

    general_menu.add_command(label='Set Username', command=on_set_username)
    general_menu.add_command(label='Join Room', command=on_join_room)

    general_menu.add_cascade(label='New...', menu=new_submenu)

    new_submenu.add_command(label='Direct Message', command=on_create_direct)
    new_submenu.add_command(label='Room', command=on_create_room)

    general_menu.add_cascade(label='Leave...', menu=leave_menu)

    leave_menu.add_command(label='Direct Message', command=on_leave_direct)
    leave_menu.add_command(label='Room', command=on_leave_room)

    general_menu.add_separator()

    general_menu.add_command(label='Disconnect', command=on_disconnect)

    menubar.add_cascade(label=menubar_label, menu=general_menu)

    copy_menu.add_command(label='User UUID', command=on_copy_user_menu_pressed)
    copy_menu.add_command(label='Channel UUID', command=on_copy_channel_pressed)

    menubar.add_cascade(label='Copy', menu=copy_menu)

    menubar.add_command(label='Help', command=on_help_menu_pressed)

    menubar.entryconfig(menubar_label, state=tkinter.DISABLED)

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.config(menu=menubar)

    #for widget in root.winfo_children():
    #    if widget.winfo_children():
    #        if 'bg' in widget.configure():
    #            widget.configure(bg='blue')
    #    if 'bg' in widget.configure():
    #        widget.configure(bg='blue')
        
    #root.configure(bg='blue')
    #main_menu.configure(bg='blue')
    #connect_menu.configure(bg='blue')
    #connected_layout.configure(bg='blue')
    root.mainloop()
