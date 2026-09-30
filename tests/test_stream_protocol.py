import struct
import unittest

from contacter_wire.stream_protocol import (
    HEADER_SIZE,
    MAX_FRAME_SIZE,
    Frame,
    FrameType,
    ProtocolError,
    StreamParser,
    decode_frame,
    encode_frame,
)


class StreamProtocolTests(unittest.TestCase):
    def test_round_trip_and_frame_types(self):
        frame = Frame(FrameType.DATA, 42, b"abc")
        raw = encode_frame(frame)
        self.assertEqual(decode_frame(raw), frame)
        self.assertEqual(decode_frame(encode_frame(FrameType.PING)).frame_type, FrameType.PING)

    def test_parser_handles_partial_and_sticky_frames(self):
        first = encode_frame(FrameType.OPEN, 1, b"one")
        second = encode_frame(FrameType.CLOSE, 2, b"two")
        parser = StreamParser()
        self.assertEqual(parser.feed(first[:2]), [])
        self.assertEqual(parser.feed(first[2:] + second), [Frame(FrameType.OPEN, 1, b"one"), Frame(FrameType.CLOSE, 2, b"two")])
        self.assertEqual(parser.buffered_bytes, 0)

    def test_close_rejects_partial_frame(self):
        parser = StreamParser()
        parser.feed(encode_frame(FrameType.DATA, 1, b"data")[:-1])
        with self.assertRaisesRegex(ProtocolError, "truncated"):
            parser.close()

    def test_limits_and_invalid_lengths(self):
        with self.assertRaises(ProtocolError):
            encode_frame(FrameType.DATA, 1, b"x" * (MAX_FRAME_SIZE - HEADER_SIZE + 1))
        with self.assertRaises(ProtocolError):
            decode_frame(struct.pack("!I", HEADER_SIZE - 1) + b"x" * (HEADER_SIZE - 1))
        with self.assertRaises(ProtocolError):
            StreamParser(max_frame_size=HEADER_SIZE).feed(struct.pack("!I", HEADER_SIZE + 1))
        with self.assertRaises(ProtocolError):
            decode_frame(encode_frame(99, 1))

    def test_decode_requires_exactly_one_frame(self):
        raw = encode_frame(FrameType.DATA, 1, b"x")
        with self.assertRaises(ProtocolError):
            decode_frame(raw[:-1])
        with self.assertRaises(ProtocolError):
            decode_frame(raw + b"extra")


if __name__ == "__main__":
    unittest.main()
