# Use Instructions
## Dependencies
Tk/Tcl for Python 3.14
## File Structure
```
main
|_ messaging_modules
  |_ status.py
  |_ functions.py
|_ messaging_server.py
|_ messaging_client.py
|_ test_server.crt
|_ test_server.key
|_ server_config.ini
```
The `messaging_modules` folder contains `status.py` and `functions.py` which are modules that contain shared constants and functions respectively.
The `messaging_server.py` program is the messaging server that facilitates the processing, handling, and moderation of the messages and the server itself.
The `messaging_client.py` program is for people to use to connect to the server to message others!
The other files (`test_server.crt`, `test_server.key`, `server_config.ini`) are used for TLS and the configuration of the server.
## Execution
The `messaging_server.py` program should be started first, with the `test_server.crt`, `test_server.key`, and `server_config.ini` in the same working directory as the program.
The server program will create any other missing folders and files. The configured common name in `server_config.ini` should be `test_server` as that is the common name the certificate has been generated with.
Visit https://docs.python.org/3/library/ssl.html#self-signed-certificates if you want to generate a self-signed certificate.

The `messaging_client.py` program then can be run and you can connect to the server with it (e.g. IP: 127.0.0.1, TCP: 38119 from default configuration).
The client program will create any missing folders and configuration file if needed.
