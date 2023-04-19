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
        self.log_file = open("Sender_log.txt", "w")
        self.start_time = None
        self.end_of_transmission = threading.Event()
        self.connection_terminated = threading.Event()
        self.fin_ack_received = threading.Event()

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
        self.send_fin(self.next_seq_num)

        # Wait for the FIN-ACK to be received in the handle_ack() function
        self.fin_ack_received.wait()

        self.next_seq_num = self.next_seq_num + 1

        # Set the connection_terminated flag to break the handle_ack() loop
        self.connection_terminated.set()

    def handle_ack(self):
        while not self.connection_terminated.is_set():  # Modify the loop condition
            try:
                data, _ = self.sock.recvfrom(4096)
                segment = STPSegment.from_bytes(data)

                if segment.segment_type == 1:
                    with self.lock:
                        self.log("rcv", 1, segment.seq_num, 0)

                        if segment.seq_num > self.window_base:
                            self.window_base = segment.seq_num

                            # Remove acknowledged segments from the window
                            seq_nums_to_remove = [seq_num for seq_num in self.window if seq_num < self.window_base]
                            for seq_num in seq_nums_to_remove:
                                del self.window[seq_num]

                        if self.next_seq_num + 1 == segment.seq_num:  # Check if FIN-ACK is received
                            self.fin_ack_received.set()  # Set the flag for FIN-ACK

            except socket.timeout:
                continue


    def send_data(self):
        with open(self.file_to_send, "rb") as file:
            while True:
                with self.lock:
                    # Check if the current seq_num is within the window
                    if self.next_seq_num < self.window_base + self.max_win:
                        # Read the next chunk of data from the file
                        data_chunk = file.read(1000)
                        
                        # Break the loop if the file is completely read
                        if not data_chunk:
                            break

                        # Create a new data packet and send it
                        segment = STPSegment(seq_num=self.next_seq_num, payload=data_chunk)
                        self.sock.sendto(segment.to_bytes(), ('localhost', self.receiver_port))
                        self.log("snd", 0, self.next_seq_num, len(data_chunk))

                        # Add the packet to the window and start its timer
                        self.window[self.next_seq_num] = (segment, time.time())
                        self.next_seq_num += len(data_chunk)

                    # Check for timed-out segments and retransmit them
                    current_time = time.time()
                    for seq_num, (segment, timestamp) in self.window.items():
                        if current_time - timestamp > self.rto:
                            self.sock.sendto(segment.to_bytes(), ('localhost', self.receiver_port))
                            self.log("snd", 0, seq_num, len(segment.payload))
                            self.window[seq_num] = (segment, current_time)
                
                self.end_of_transmission.set()

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

        print("Connection terminated successfully.")

if __name__ == "__main__":
    main()