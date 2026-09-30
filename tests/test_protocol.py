import time, unittest
from contacter.protocol import Message, encode, decode, make
from contacter.auth import ReplayCache

class ProtocolTests(unittest.TestCase):
    def test_round_trip(self):
        secret=b'x'*32; p=make(Message.DATA,42,b'abc')
        self.assertEqual(decode(encode(p,secret),secret,now=time.time()).payload,b'abc')
    def test_bad_tag(self):
        secret=b'x'*32; raw=bytearray(encode(make(Message.DATA),secret)); raw[-1]^=1
        with self.assertRaises(ValueError): decode(bytes(raw),secret,now=time.time())
    def test_replay_cache(self):
        c=ReplayCache(ttl=10); self.assertFalse(c.seen('a',1,0)); self.assertTrue(c.seen('a',1,1)); self.assertFalse(c.seen('a',1,11))

if __name__=='__main__': unittest.main()
