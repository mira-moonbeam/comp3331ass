import sys
import socket
import time
import argparse
from STPSegment import STPSegment
import threading

class Sender:
    def __init__(self, sender_port, receiver_port, file_to_send, max_win, rto):
        self.sender_port = sender_port
        self.receiver_port = receiver_port
        self.file_to_send = file_to_send
        self.max_win = max_win
        self.rto = rto

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('localhost', self.sender_port))
        self.sock.settimeout(0.5)
        self.ISN = 0
        self.log_file = open("sender_log.txt", "w")
        self.start_time = None

        self.window_base = 0
        self.next_seq_num = 0
        self.lock = threading.Lock()
        self.window = {}

    def log(self, snd_rcv, packet_type, seq_num, num_bytes):
        current_time = time.time()
        elapsed_time = round(current_time - self.start_time, 5) if self.start_time is not None else 0
        pack_type = "DATA"

        if packet_type==1:
            pack_type = "ACK"
        elif packet_type==2:
            pack_type = "SYN"
        elif packet_type==3:
            pack_type = "FIN"
        elif packet_type==4:
            pack_type = "RESET"

        log_str = f"{snd_rcv} {elapsed_time}s {pack_type} {seq_num} {num_bytes}\n"
        self.log_file.write(log_str)

    # DATA = 0, ACK = 1, SYN = 2, FIN = 3, RESET = 4
    def send_syn(self, seq_num):
        segment = STPSegment(seq_num=seq_num, segment_type=2)
        self.sock.sendto(segment.to_bytes(), ('localhost', self.receiver_port))
        self.log("snd", 2, seq_num, 0)
        

    def send_fin(self, seq_num):
        segment = STPSegment(seq_num=seq_num, segment_type=3)
        self.sock.sendto(segment.to_bytes(), ('localhost', self.receiver_port))

        self.log("snd", 3, seq_num, 0)

    def connection_establish(self):
        retry_count = 0
        self.start_time = time.time()
        while retry_count < 3:
            try:
                self.send_syn(self.ISN)
                
                data, _ = self.sock.recvfrom(4096)
                segment = STPSegment.from_bytes(data)

                if segment.segment_type==1:
                    self.log("rcv", 1, segment.seq_num, 0)
                    
                    self.next_seq_num = self.ISN + 1
                    return True
                
            except socket.timeout:
                print("SOCKET TIMEOUT DURING CONNECTION ESTABLISHING")
                retry_count += 1
        
        return False
    
    def connection_terminate(self):
        retry_count = 0
        while retry_count < 3:
            try:
                self.send_fin(self.next_seq_num)
                print(self.next_seq_num)
                data, _ = self.sock.recvfrom(4096)
                segment = STPSegment.from_bytes(data)
                if segment.segment_type==1 and segment.seq_num==self.next_seq_num + 1:
                    self.log("rcv", 1, segment.seq_num, 0)

                    self.next_seq_num = self.next_seq_num + 1
                    return True
                
            except socket.timeout:
                print("SOCKET TIMEOUT DURING CONNECTION TERMINATION")
                retry_count += 1
        
        return False

    def handle_ack(self):
        while True:
            try:
                data, _ = self.sock.recvfrom(4096)
                segment = STPSegment.from_bytes(data)

                if segment.segment_type == 1:
                    with self.lock:
                        self.log("rcv", 1, segment.seq_num, 0)

                        if segment.seq_num > self.window_base:
                            self.window_base = segment.seq_num
                            # Remove acknowledged segments from the window
                            for seq_num in range(self.window_base - self.max_win, self.window_base):
                                if seq_num in self.window:
                                    del self.window[seq_num]

            except socket.timeout:
                continue

    def send_data(self):
        if self.connection_establish():
            # Start a thread to handle received ACKs
            ack_thread = threading.Thread(target=self.handle_ack, daemon=True)
            ack_thread.start()

            with open(self.file_to_send, 'rb') as file:
                while True:
                    with self.lock:
                        while self.next_seq_num < self.window_base + self.max_win:
                            filedata = file.read(1000)

                            if not filedata:
                                break

                            segment = STPSegment(seq_num=self.next_seq_num, payload=filedata, segment_type=0)
                            self.sock.sendto(segment.to_bytes(), ('localhost', self.receiver_port))
                            self.log("snd", 0, self.next_seq_num, len(filedata))

                            self.window[self.next_seq_num] = (time.time(), segment.to_bytes())
                            self.next_seq_num += len(filedata)

                    if not filedata:
                        break

                    # Retransmit unacknowledged segments
                    for seq_num, (timestamp, segment) in self.window.items():
                        if time.time() - timestamp > float(self.rto):
                            self.sock.sendto(segment, ('localhost', self.receiver_port))
                            self.log("snd", 0, seq_num, len(filedata))

            # Wait for the remaining ACKs
            while self.window_base < self.next_seq_num:
                time.sleep(0.1)

            if self.connection_terminate():
                print("COMPLETE PROGRAM")
                self.log_file.close()
                

             

def main():
    parser = argparse.ArgumentParser(description='Sender')
    parser.add_argument('sender_port', type=int, help='Sender port number')
    parser.add_argument('receiver_port', type=int, help='Receiver port number')
    parser.add_argument('file_to_send', type=str, help='File to send')
    parser.add_argument('max_win', type=int, help='Max Window Size in bytes')
    parser.add_argument('rto', type=str, help='Retransmission time')
    args = parser.parse_args()

    sender = Sender(args.sender_port, args.receiver_port, args.file_to_send, args.max_win, args.rto)
    sender.send_data()

if __name__ == "__main__":
    main()