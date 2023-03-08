import os
from functools import partial

import pytest
import torch
import torch.distributed as dist

from elixir import init_distributed
from elixir.chunk import Chunk, FIFOScheduler, MemoryPool


def exam_fifo(nproc, group):
    mp = MemoryPool('cuda')
    mp.allocate(public_block_number=1)
    c0 = Chunk(mp, 1024, torch.float, group)
    c1 = Chunk(mp, 1024, torch.float, group)
    c2 = Chunk(mp, 1024, torch.float, group)

    sdl = FIFOScheduler()
    sdl.reset()

    sdl.add(c0)
    sdl.add(c1)
    sdl.add(c2)
    sdl.add(c0)    # nothing happens here
    assert sdl.top() == c0

    sdl.remove(c0)
    assert sdl.top() == c1, f'{sdl.top()}'
    sdl.remove(c0)
    assert sdl.top() == c1, f'{sdl.top()}'

    sdl.add(c0)
    assert sdl.top() == c1
    sdl.remove(c1)
    assert sdl.top() == c2
    sdl.remove(c2)
    assert sdl.top() == c0


def run_dist(rank, world_size):
    os.environ['RANK'] = str(rank)
    os.environ['LOCAL_RANK'] = str(rank)
    os.environ['WORLD_SIZE'] = str(world_size)
    os.environ['MASTER_ADDR'] = '127.0.0.1'
    os.environ['MASTER_PORT'] = str(29512)
    init_distributed()
    exam_fifo(nproc=world_size, group=dist.GroupMember.WORLD)


@pytest.mark.dist
def test_chunk_scheduler():
    world_size = 1
    run_func = partial(run_dist, world_size=world_size)
    torch.multiprocessing.spawn(run_func, nprocs=world_size)


if __name__ == '__main__':
    test_chunk_scheduler()