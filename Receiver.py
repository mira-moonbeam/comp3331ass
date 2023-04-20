import sys
import select
import time
import socket
import argparse
import random as rnd
import threading
from STPSegment import STPSegment

class Receiver:
    def __init__(self, receiver_port, sender_port, file_to_write, flp, rlp):
        self.receiver_port = receiver_port
        self.sender_port = sender_port
        self.file_to_write = file_to_write
        self.flp = flp
        self.rlp = rlp

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('localhost', self.receiver_port))
        self.sequence = 0

        self.log_file = open("receiver_log.txt", "w")
        self.start_time = None

        self.buffer_lock = threading.Lock()
        self.buffer = {}
        self.ack_timer = None
        self.ack_timeout = 0.1

        # Tracking variables
        self.original_data_bytes_received = 0
        self.original_data_segments_received = 0
        self.duplicate_data_segments_received = 0
        self.data_segments_dropped = 0
        self.ack_segments_dropped = 0

    def log(self, snd_rcv, packet_type, seq_num, num_bytes):
        current_time = time.time()
        elapsed_time = round((current_time - self.start_time) * 1000, 2) if self.start_time is not None else 0
        pack_type = "DATA"

        if packet_type==1:
            pack_type = "ACK"
        elif packet_type==2:
            pack_type = "SYN"
        elif packet_type==3:
            pack_type = "FIN"
        elif packet_type==4:
            pack_type = "RESET"

        log_str = f"{snd_rcv:<3} {elapsed_time:<10} {pack_type:<6} {seq_num:<8} {num_bytes}\n"
        self.log_file.write(log_str)

    # DATA = 0, ACK = 1, SYN = 2, FIN = 3, RESET = 4
    def send_ack(self, seq_num):
        if rnd.random() > self.rlp:
            segment = STPSegment(seq_num=seq_num, segment_type=1)
            self.sock.sendto(segment.to_bytes(), ('localhost', self.sender_port))
            self.log("snd", 1, seq_num, 0)
        else:
            self.ack_segments_dropped += 1

    def send_cumulative_ack(self):
        with self.buffer_lock:
            self.send_ack(self.sequence)

    def reset_ack_timer(self):
        if self.ack_timer is not None:
            self.ack_timer.cancel()
        self.ack_timer = threading.Timer(self.ack_timeout, self.send_cumulative_ack)
        self.ack_timer.start()

    def receive_data(self):
        
        syn_ack_sent = False
        start_time_initialized = False

        while True:
            timeout = 2 if syn_ack_sent else None
            ready_to_read, _, _ = select.select([self.sock], [], [], timeout) # please dont ask - i googled it
            if not ready_to_read:
                if syn_ack_sent or start_time_initialized:
                    break  # Exit the loop if there are no incoming packets after 2 seconds
                else:
                    continue  # Keep waiting for the SYN packet

            data, _ = self.sock.recvfrom(4096)
            segment = STPSegment.from_bytes(data)

            # even if the first syn is dropped it should just start the timer anyway even though technically
            # it would KNOW it received anythign im just gonna assume they want me to start there
            if not start_time_initialized:
                self.start_time = time.time()
                start_time_initialized = True

            if segment.segment_type == 4:
                if rnd.random() > self.flp:
                    self.log("rcv", 4, 0, 0)
                    print("RESET FLAG RECEIVED")
                    break

            if segment.segment_type == 2:
                # SYN HANDLE
                if rnd.random() > self.flp:
                    self.log("rcv", 2, segment.seq_num, 0)
                    
                    self.sequence = (segment.seq_num + 1) % 2**16
                    self.send_ack(self.sequence)
                    syn_ack_sent = True
                else:
                    # dookie syns dont get to start the clock :(((
                    self.log("drp", 2, segment.seq_num, 0)

            elif segment.segment_type == 3:
                # FIN HANDLE
                if rnd.random() > self.flp:
                    self.log("rcv", 3, segment.seq_num, 0)
                    self.send_ack(segment.seq_num + 1)
                else:
                    self.log("drp", 3, segment.seq_num, 0)

            elif segment.segment_type == 0:
                payload_length = len(segment.payload)

                if rnd.random() > self.flp:
                    self.log("rcv", 0, segment.seq_num, payload_length)

                    with self.buffer_lock:
                        if segment.seq_num == self.sequence:
                            self.buffer[segment.seq_num] = segment.payload
                            self.sequence = (self.sequence + payload_length) % 2**16
                            self.reset_ack_timer()

                            # Update tracking variables
                            self.original_data_bytes_received += payload_length
                            self.original_data_segments_received += 1

                        elif segment.seq_num > self.sequence:
                            self.buffer[segment.seq_num] = segment.payload
                            self.send_ack(self.sequence)  # Send ACK for the expected sequence number

                            # Update tracking variables
                            self.duplicate_data_segments_received += 1

                        elif segment.seq_num < self.sequence:
                            self.send_ack(self.sequence)

        with self.buffer_lock:
            with open(self.file_to_write, 'wb') as file:
                for _, payload in sorted(self.buffer.items()):
                    file.write(payload)
    
    def log_statistics(self):
        stats = f"\n--- Statistics ---\nOriginal Data Received: {self.original_data_bytes_received}\nOriginal Data Segments Received: {self.original_data_segments_received}\nDuplicate Data Segments Received: {self.duplicate_data_segments_received}\nData Segments Dropped: {self.data_segments_dropped}\nACKs Dropped: {self.ack_segments_dropped}\n"
        self.log_file.write(stats)
        self.log_file.flush()

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

    receiver.log_statistics()

    receiver.log_file.close()

if __name__ == "__main__":
    main()