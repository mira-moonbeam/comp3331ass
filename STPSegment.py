import struct

class STPSegment:
    def __init__(self, seq_num=0, payload=b'', segment_type=0):
        self.seq_num = seq_num
        self.payload = payload
        self.segment_type = segment_type

    def to_bytes(self):
        header = struct.pack('!HH', self.seq_num, self.segment_type)
        return header + self.payload

    @classmethod
    def from_bytes(cls, data):
        header = data[:4]
        payload = data[4:]
        seq_num, segment_type = struct.unpack('!HH', header)
        return cls(seq_num=seq_num, payload=payload, segment_type=segment_type)
