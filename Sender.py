import sys
import socket
import time
import random
import argparse
from STPSegment import STPSegment
import threading

class Sender:
    def __init__(self, sender_port, receiver_port, file_to_send, max_win, rto):
        self.sender_port = sender_port
        self.receiver_port = receiver_port
        self.file_to_send = file_to_send
        self.max_win = max_win
        self.rto = rto/1000

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('localhost', self.sender_port))
        self.sock.settimeout(self.rto)

        # Actual variabls i need to use for the code to work
        self.ISN = random.randint(0, 2**16 - 1)
        self.window_base = 0
        self.next_seq_num = 0
        self.window = {}
        
        # Threading stuff
        self.end_of_transmission = threading.Event()
        self.connection_terminated = threading.Event()
        self.fin_ack_received = threading.Event()
        self.lock = threading.Lock()

        # Tracking variables
        self.log_file = open("Sender_log.txt", "w")
        self.start_time = None
        self.original_data_transferred = 0
        self.data_segments_sent = 0
        self.retransmitted_data_segments = 0
        self.duplicate_acks_received = 0

    def log(self, snd_rcv, packet_type, seq_num, num_bytes):
        current_time = time.time()
        elapsed_time = round((current_time - self.start_time)*1000, 2) if self.start_time is not None else 0
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
        self.log_file.flush()

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
        start_initialized = False
        reset = 0
        while reset < 3:
            self.send_syn(self.ISN)
            if not start_initialized:
                self.start_time = time.time()
                start_initialized = True

            try:
                data, _ = self.sock.recvfrom(4096)
                segment = STPSegment.from_bytes(data)

                if segment.segment_type == 1:
                    self.log("rcv", 1, segment.seq_num, 0)

                    self.next_seq_num = (self.ISN + 1) % 2**16
                    self.window_base = (self.ISN + 1) % 2**16
                    return True

            except socket.timeout:
                reset += 1
                
        segment = STPSegment(seq_num=0, segment_type=4)
        self.sock.sendto(segment.to_bytes(), ('localhost', self.receiver_port))
        self.log("snd", 4, 0, 0)  
        print("CONNECTION GONE")

    def connection_terminate(self):
        reset = 0
        while not self.fin_ack_received.is_set() and reset < 3:
            self.send_fin(self.next_seq_num)

            try:
                data, _ = self.sock.recvfrom(4096)
                segment = STPSegment.from_bytes(data)

                if segment.segment_type == 1 and (self.next_seq_num + 1) % 2**16 == segment.seq_num:
                    self.log("rcv", 1, segment.seq_num, 0)
                    self.fin_ack_received.set()
                    self.end_of_transmission.set()

            except socket.timeout:
                reset += 1
        
        if not self.fin_ack_received.is_set():
            segment = STPSegment(seq_num=0, segment_type=4)
            self.sock.sendto(segment.to_bytes(), ('localhost', self.receiver_port))
            self.log("snd", 4, 0, 0)  

        self.next_seq_num = (self.next_seq_num + 1) % 2**16
        self.connection_terminated.set()

    def handle_ack(self):
        last_ack = None
        while not self.connection_terminated.is_set():
            try:
                data, _ = self.sock.recvfrom(4096)
                segment = STPSegment.from_bytes(data)

                if segment.segment_type == 1:
                    with self.lock:
                        self.log("rcv", 1, segment.seq_num, 0)

                        if segment.seq_num >= self.window_base:
                            self.window_base = segment.seq_num

                            # Remove acknowledged segments from the window
                            seq_nums_to_remove = [seq_num for seq_num in list(self.window.keys()) if seq_num < self.window_base]
                            for seq_num in seq_nums_to_remove:
                                del self.window[seq_num]
                        
                        # Track duplicate ACKs
                        if last_ack is not None and segment.seq_num == last_ack:
                            self.duplicate_acks_received += 1
                        last_ack = segment.seq_num

                        if (self.next_seq_num + 1) % 2**16 == segment.seq_num:  # Check if FIN-ACK is received
                            self.fin_ack_received.set()  # Set the flag for FIN-ACK

            except socket.timeout:
                pass

            # Retransmit unacknowledged segments
            current_time = time.time()
            window_keys = list(self.window.keys())  # Create a copy of dictionary keys
            for seq_num in window_keys:
                if seq_num not in self.window:  # Check if the seq_num is still in the window
                    continue

                segment, timestamp = self.window[seq_num]
                if current_time - timestamp > self.rto:
                    with self.lock:

                        self.retransmitted_data_segments += 1

                        self.sock.sendto(segment.to_bytes(), ('localhost', self.receiver_port))
                        self.log("snd", 0, seq_num, len(segment.payload))
                        self.window[seq_num] = (segment, current_time)

                    # Wait for ACK after resending the packet
                    while True:
                        try:
                            data, _ = self.sock.recvfrom(4096)
                            segment = STPSegment.from_bytes(data)

                            if segment.segment_type == 1:
                                with self.lock:
                                    self.log("rcv", 1, segment.seq_num, 0)
                                    # Track duplicate ACKs
                                    if last_ack is not None and segment.seq_num == last_ack:
                                        self.duplicate_acks_received += 1
                                    last_ack = segment.seq_num

                                    if segment.seq_num >= self.window_base:
                                        self.window_base = segment.seq_num

                                        # Remove acknowledged segments from the window
                                        seq_nums_to_remove = [seq_num for seq_num in list(self.window.keys()) if seq_num < self.window_base]
                                        for seq_num in seq_nums_to_remove:
                                            del self.window[seq_num]

                                    break
                        except socket.timeout:
                            # Resend the packet if ACK is not received
                            with self.lock:
                                self.retransmitted_data_segments += 1

                                self.sock.sendto(segment.to_bytes(), ('localhost', self.receiver_port))
                                self.log("snd", 0, seq_num, len(segment.payload))
                                self.window[seq_num] = (segment, current_time)

    def send_data(self):
        with open(self.file_to_send, "rb") as file:
            data_chunk = None
            first_iteration = True
            while first_iteration or data_chunk:
                with self.lock:
                    temp_window = []
                    
                    # Create all packets in the window
                    while self.next_seq_num < (self.window_base + self.max_win) % 2 ** 16:
                        data_chunk = file.read(1000)

                        # Send at least one segment, even if the file is empty
                        if not data_chunk and not first_iteration:
                            self.end_of_transmission.set()
                            break

                        # Create a new data packet
                        self.original_data_transferred += len(data_chunk)
                        self.data_segments_sent += 1
                        segment = STPSegment(seq_num=self.next_seq_num, payload=data_chunk)

                        # Add the packet to the temporary window
                        temp_window.append((self.next_seq_num, segment))
                        self.next_seq_num = (self.next_seq_num + len(data_chunk)) % 2**16

                        first_iteration = False

                    # Send all packets in the temporary window
                    for seq_num, segment in temp_window:
                        if seq_num < self.window_base:
                            continue

                        self.sock.sendto(segment.to_bytes(), ('localhost', self.receiver_port))
                        self.log("snd", 0, seq_num, len(segment.payload))

                        # Add the packet to the timer window
                        self.window[seq_num] = (segment, time.time())
                    
                    if not data_chunk:
                        break

        self.end_of_transmission.set()
                        
    def log_statistics(self):
        stats = f"\n--- Statistics ---\nOriginal Data Transferred: {self.original_data_transferred}\nData Segments Sent: {self.data_segments_sent}\nRetransmitted Data Segments: {self.retransmitted_data_segments}\nDuplicate ACKs Received: {self.duplicate_acks_received}\n"
        self.log_file.write(stats)
        self.log_file.flush()

    def terminate_on_completion(self):
        self.end_of_transmission.wait()

        while self.window_base < self.next_seq_num:
            time.sleep(0.1)

        if self.connection_terminate():  # Check if the connection has been terminated
            self.connection_terminated.set()
 
def main():
    parser = argparse.ArgumentParser(description='Sender')
    parser.add_argument('sender_port', type=int, help='Sender port number')
    parser.add_argument('receiver_port', type=int, help='Receiver port number')
    parser.add_argument('file_to_send', type=str, help='File to send')
    parser.add_argument('max_win', type=int, help='Max Window Size in bytes')
    parser.add_argument('rto', type=float, help='Retransmission time')
    args = parser.parse_args()

    sender = Sender(args.sender_port, args.receiver_port, args.file_to_send, args.max_win, args.rto)

    if sender.connection_establish():
        ack_thread = threading.Thread(target=sender.handle_ack)
        send_thread = threading.Thread(target=sender.send_data)
        termination_thread = threading.Thread(target=sender.terminate_on_completion)

        ack_thread.start()
        send_thread.start()
        termination_thread.start()

        ack_thread.join()
        send_thread.join()
        termination_thread.join()

        sender.log_statistics()

if __name__ == "__main__":
    main()