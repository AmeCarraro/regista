"""Carries a port of this container to a port elsewhere: python3 forward.py 8443 host.docker.internal 8443

The pretend phone sees the machine it runs on as 10.0.2.2, and that machine is this
container. The computer's door for the phones is on the PC, outside: this brings it in.
"""
import asyncio
import sys


async def carry(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except OSError:
        pass
    finally:
        writer.close()


async def main(port: int, host: str, there: int) -> None:
    async def arrive(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            far_reader, far_writer = await asyncio.open_connection(host, there)
        except OSError:
            writer.close()
            return
        await asyncio.gather(carry(reader, far_writer), carry(far_reader, writer))

    async with await asyncio.start_server(arrive, "0.0.0.0", port) as server:
        await server.serve_forever()


asyncio.run(main(int(sys.argv[1]), sys.argv[2], int(sys.argv[3])))
