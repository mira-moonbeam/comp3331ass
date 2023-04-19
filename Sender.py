import sys
import socket
import time
import argparse
from STPSegment import STPSegment

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
                    
                    self.ISN = self.ISN + 1
                    return True
                
            except socket.timeout:
                print("SOCKET TIMEOUT DURING CONNECTION ESTABLISHING")
                retry_count += 1
        
        return False
    
    def connection_terminate(self):
        retry_count = 0
        while retry_count < 3:
            try:
                self.send_fin(self.ISN)
                
                data, _ = self.sock.recvfrom(4096)
                segment = STPSegment.from_bytes(data)
                if segment.segment_type==1 and segment.seq_num==self.ISN + 1:
                    self.log("rcv", 1, segment.seq_num, 0)

                    self.ISN = self.ISN + 1
                    return True
                
            except socket.timeout:
                print("SOCKET TIMEOUT DURING CONNECTION TERMINATION")
                retry_count += 1
        
        return False

    def send_data(self):
        if self.connection_establish():
            with open(self.file_to_send, 'rb') as file:
                filedata = file.read(1000)
                while filedata:
                    segment = STPSegment(seq_num=self.ISN, payload=filedata, segment_type=0)
                    self.sock.sendto(segment.to_bytes(), ('localhost', self.receiver_port))
                    self.log("snd", 0, self.ISN, len(filedata))
                    # new seq num if the send works
                    temp_seq = self.ISN + len(filedata)

                    ack_received = False

                    while not ack_received:
                        try:
                            data, _ = self.sock.recvfrom(4096)
                            segment = STPSegment.from_bytes(data)
                            self.log("rcv", 1, segment.seq_num, 0)

                            if segment.seq_num >= temp_seq:
                                # The seq number in the ack matches or is ahead of the one we are about to send out
                                ack_received = True
                                self.ISN = segment.seq_num
                                temp_seq = segment.seq_num
                            else:
                                # oh our dat wasnt lost their ack was lost so now they're ahead of us
                                pass
                                
                        except socket.timeout:
                            # Didnt receive an ack so we can only assume our sent data was lost so resend
                            segment = STPSegment(seq_num=self.ISN, payload=filedata, segment_type=0)
                            self.sock.sendto(segment.to_bytes(), ('localhost', self.receiver_port))
                            self.log("snd", 0, self.ISN, len(filedata))

                    self.ISN = temp_seq
                    time.sleep(0.05)
                    filedata = file.read(1000)
            
            # Send the end of transmission segment with FIN flag
            if self.connection_terminate():
                print("COMPLETE PROGRAM")
             

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