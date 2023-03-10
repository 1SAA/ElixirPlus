from copy import deepcopy
from test.utils import TEST_MODELS

from elixir.search import simple_search


def test_simple_search():
    builder, *_ = TEST_MODELS.get_func('small')()
    model = builder()
    sr = simple_search(model, 1, split_number=5)
    chunk_plans = deepcopy(sr.param_chunk_plans)
    private_plan = chunk_plans.pop(0)
    assert private_plan.name_list == ['embed.weight']
    assert private_plan.chunk_size == 320

    assert chunk_plans[0].name_list == ['norm1.weight', 'norm1.bias']
    assert chunk_plans[1].name_list == ['mlp.proj1.weight', 'mlp.proj1.bias']
    assert chunk_plans[2].name_list == ['mlp.proj2.weight', 'mlp.proj2.bias']
    assert chunk_plans[3].name_list == ['norm2.weight']
    assert chunk_plans[4].name_list == ['norm2.bias']

    for plan in chunk_plans:
        assert plan.chunk_size == 1088


if __name__ == '__main__':
    test_simple_search()
