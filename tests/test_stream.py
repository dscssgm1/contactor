import asyncio
import pathlib
import sys
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / 'server_distribution' / 'src'))
from contacter_wire.stream import read_frame, write_frame

class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_round_trip(self):
        secret=b'x'*32
        async def handler(reader, writer):
            frame=await read_frame(reader, secret)
            self.assertEqual(frame,(7,42,b'hello'))
            await write_frame(writer,secret,*frame)
            writer.close()
        server=await asyncio.start_server(handler,'127.0.0.1',0)
        host,port=server.sockets[0].getsockname()[:2]
        reader,writer=await asyncio.open_connection(host,port)
        await write_frame(writer,secret,7,42,b'hello')
        self.assertEqual(await read_frame(reader,secret),(7,42,b'hello'))
        writer.close(); server.close(); await server.wait_closed()

    async def test_bad_tag_rejected(self):
        secret=b'x'*32
        async def handler(reader, writer):
            with self.assertRaises(ValueError): await read_frame(reader,secret)
            writer.close()
        server=await asyncio.start_server(handler,'127.0.0.1',0)
        host,port=server.sockets[0].getsockname()[:2]
        reader,writer=await asyncio.open_connection(host,port)
        await write_frame(writer,b'y'*32,7,1,b'x')
        await asyncio.sleep(0.01)
        writer.close(); server.close(); await server.wait_closed()

if __name__=='__main__': unittest.main()
