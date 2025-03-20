import socket
import re
import cv2
import numpy as np
import time

#https://github.com/luxonis/depthai-experiments/blob/master/gen2-poe-tcp-streaming/host.py

#TODO: look at implementation of earlier version of this script to add better periodic timing
#TODO: add option of saving to arbitrary library
#TODO: add display and saving of other streams that will be added (depth, point cloud, nn-data)
#TODO: make a docker container
#TODO: add zenoh support

#TODO: need a safer way to connect to the camera with multiple retries within a timeout, maybe depend on exception type

# Enter your own IP! Note no libraries from luxonis are needed for this script
OAK_IP = "192.168.3.13"

def get_frame(socket, size):
    bytes = socket.recv(4096)
    while True:
        read = 4096
        if size-len(bytes) < read:
            read = size-len(bytes)
        bytes += socket.recv(read)
        if size == len(bytes):
            return bytes


def connect_to_oak(ip, port, timeout=60):
    sock = socket.socket()
    socket_timeout = 10
    sock.settimeout(socket_timeout)  # Set a timeout for socket operations
    start_time = time.time() #set a timout for the connection attempt as a whole
    print(f"Will try for {timeout} seconds")    
    while True:
        try:
            print(f"{int(time.time() - start_time)}: Attempting to connect to", ip)
            sock.connect((ip, port))
            print(f"{int(time.time() - start_time)}: Connected to", ip)
            return sock
        except Exception as e:
            #e: Connection failed: timed out
            #e: Connection failed: [Errno 114] Operation already in progress
            #e
            print(f"{int(time.time() - start_time)}: Connection failed:", e)
            if time.time() - start_time > timeout:
                print("Failed to connect within {timeout} seconds.")
                return None
            time.sleep(socket_timeout)

# Usage
sock = connect_to_oak(OAK_IP, 5000)
if sock is None:
    print("Exiting due to connection failure.")
    exit(1)


try:
    while True:
        header = str(sock.recv(32), encoding="ascii")
        chunks = re.split(' +', header)
        if chunks[0] == "ABCDE":
            # print(f">{header}<")
            ts = float(chunks[1])
            imgSize = int(chunks[2])
            img = get_frame(sock, imgSize)
            buf = np.frombuffer(img, dtype=np.byte)
            # print(buf.shape, buf.size)
            frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            cv2.imshow("color", frame)
        if cv2.waitKey(1) == ord('q'):
            break
except Exception as e:
    print("Error:", e)

sock.close()
