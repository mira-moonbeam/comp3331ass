import sys
import time
import socket
import argparse
import random as rnd
from STPSegment import STPSegment

class Receiver:
    def __init__(self, receiver_port, sender_port, file_to_write, flp, rlp):
        self.receiver_port = receiver_port
        self.sender_port = sender_port
        self.file_to_write = file_to_write
        self.flp = flp
        self.rlp = rlp
        self.last_received_seq = -1

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('localhost', self.receiver_port))
        self.sequence = 0

        self.log_file = open("receiver_log.txt", "w")
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
    def send_ack(self, seq_num):
        if rnd.random() > self.rlp:
            segment = STPSegment(seq_num=seq_num, segment_type=1)
            self.sock.sendto(segment.to_bytes(), ('localhost', self.sender_port))
        else:
            self.log("drp", 1, seq_num, 0)

        self.log("snd", 1, seq_num, 0)

    def get_bytes(self, s):
        return len(s.encode('utf-8'))

    def receive_data(self):
        while True:
            # receiving a syn
            data, _ = self.sock.recvfrom(1024)
            segment = STPSegment.from_bytes(data)

            self.start_time = time.time()
            # if it's a SYN AND it's not dropped
            if segment.segment_type==2 and rnd.random() > self.flp:

                self.log("rcv", 2, segment.seq_num, 0)
                self.sequence = segment.seq_num + 1
                self.send_ack(self.sequence)

                with open(self.file_to_write, 'w') as file:
                    while True:
                        data, _ = self.sock.recvfrom(4096)
                        segment = STPSegment.from_bytes(data)

                        if segment.segment_type==3:
                                if rnd.random() > self.flp:
                                    print("somehow you made it lol")
                                    self.log("rcv", 3, segment.seq_num, 0)
                                    # Send ACK for the FIN segment
                                    self.sequence = self.sequence + 1
                                    self.send_ack(self.sequence)
                                    break
                                else:
                                    self.log("drp", 3, segment.seq_num, 0)

                        else:
                            payload_length = len(segment.payload)

                            # Check for unnecessary retransmissions
                            if segment.seq_num <= self.last_received_seq:
                                # Drop the retransmitted packet and send an ACK for the next expected sequence number
                                self.log("drp", 0, segment.seq_num, payload_length)
                                self.send_ack(self.sequence)
                            else:
                                if rnd.random() > self.flp:
                                    self.log("rcv", 0, segment.seq_num, payload_length)
                                    file.write(segment.payload.decode('utf-8') + '\n')

                                    self.last_received_seq = segment.seq_num
                                    self.sequence = self.sequence + payload_length
                                    self.send_ack(self.sequence)
                                else:
                                    print("lmao packet d rop loser")
                                    self.log("drp", 0, segment.seq_num, payload_length)
            else:
                self.log("drp", 2, segment.seq_num, 0)

            if segment.segment_type==3:
                break
                        

                    

def main():
    parser = argparse.ArgumentParser(description='Simple Stop-and-Wait Receiver')
    parser.add_argument('receiver_port', type=int, help='Receiver port number')
    parser.add_argument('sender_port', type=int, help='Sender port number')
    parser.add_argument('file_to_write', type=str, help='File to write received data')
    parser.add_argument('flp', type=float, help='Forward Loss Probability')
    parser.add_argument('rlp', type=float, help='Reverse Loss Probability')

    args = parser.parse_args()
    receiver = Receiver(args.receiver_port, args.sender_port, args.file_to_write, args.flp, args.rlp)
    receiver.receive_data()

if __name__ == "__main__":
    main()