from collections import OrderedDict
from copy import copy

import torch
import torch.nn as nn
from torch.fx.immutable_collections import immutable_dict
from torch.utils._pytree import tree_map

from elixir.parameter import OutplaceTensor, is_tensor_output, to_outplace_tensor


class FakeTensor(torch.Tensor):

    @staticmethod
    def __new__(cls, elem, *args, **kwargs):
        r = torch.Tensor._make_wrapper_subclass(cls,
                                                elem.size(),
                                                strides=elem.stride(),
                                                storage_offset=elem.storage_offset(),
                                                dtype=elem.dtype,
                                                layout=elem.layout,
                                                device=elem.device,
                                                requires_grad=elem.requires_grad)
        return r

    @classmethod
    def __torch_dispatch__(cls, func, types, args=(), kwargs=None):
        raise NotImplementedError


class PreFwdPostBwd(torch.autograd.Function):

    @staticmethod
    def forward(ctx, params, *args):
        ctx.params = params
        for p in ctx.params:
            p.data = p.my_data
        return args

    @staticmethod
    def backward(ctx, *grads):
        return (None, *grads)


class PostFwdPreBwd(torch.autograd.Function):

    @staticmethod
    def forward(ctx, params, *args):
        ctx.params = params
        for p in ctx.params:
            p.data = p.fake_data
        return args

    @staticmethod
    def backward(ctx, *grads):
        for p in ctx.params:
            p.data = p.my_data
        return (None, *grads)


class MyParameter(OutplaceTensor):

    def __new__(cls, tensor, requires_grad=True):
        r = torch.Tensor._make_subclass(cls, tensor, require_grad=requires_grad)
        if isinstance(tensor, nn.Parameter):
            r = nn.Parameter(r)
        with torch._C.DisableTorchFunction():
            r.my_shape = tensor.shape
            r.my_dtype = tensor.dtype
            r.my_device = tensor.device
            r.my_data = r.data
            r.fake_data = FakeTensor(r.my_data)
            r.data = r.fake_data
        return r

    @classmethod
    def __torch_function__(cls, func, types, args=(), kwargs=None):
        if kwargs is None:
            kwargs = {}

        if is_tensor_output(func):
            with torch._C.DisableTorchFunction():
                ret = func(*args, **kwargs)
            return ret

        params_to_index = OrderedDict()
        params_index = 0

        def append_param(x):
            nonlocal params_index
            if isinstance(x, MyParameter):
                params_to_index[x] = params_index
                params_index += 1

        tree_map(append_param, args)
        tree_map(append_param, kwargs)

        params = tuple(params_to_index.keys())
        with torch._C.DisableTorchFunction():
            new_params = PreFwdPostBwd.apply(params, *params)

        def replace_param(x):
            if isinstance(x, MyParameter):
                return new_params[params_to_index[x]]
            return x

        with torch._C.DisableTorchFunction():
            # for x in new_params:
            #     print("new_params", type(x))
            #     if isinstance(x, torch.Tensor):
            #         print(x.shape, x.dtype)
            # for x in args:
            #     print("args", type(x))
            #     if isinstance(x, torch.Tensor):
            #         print(x.shape, x.dtype)
            #
            # for k, v in kwargs.items():
            #     print("kwargs", k, v)
            #     if isinstance(v, torch.Tensor):
            #         print(v.shape, v.dtype)

            ret = func(*tree_map(replace_param, args), **tree_map(replace_param, kwargs))

        if not isinstance(ret, tuple):
            ret = (ret,)

        ptr_set = set()
        for p in new_params:
            ptr_set.add(p.data_ptr())

        def clone_inplace_tensor(x):
            if isinstance(x, torch.Tensor) and x.data_ptr() in ptr_set:
                return x.clone()
            return x

        ret = tree_map(clone_inplace_tensor, ret)
        with torch._C.DisableTorchFunction():
            ret = PostFwdPreBwd.apply(params, *ret)

        def convert(t):
            if isinstance(t, torch.Tensor):
                t = to_outplace_tensor(t)
            return t

        ret = tree_map(convert, ret)

        if len(ret) == 1:
            return ret[0]
        else:
            return ret


def transform(m: nn.Module) -> nn.Module:
    # transform each parameter to MyParameter
    for m_name, module in m.named_modules():
        param_list = list(module.named_parameters(recurse=False))
        for p_name, param in param_list:
            new_param = MyParameter(param.data)
            delattr(module, p_name)
            setattr(module, p_name, new_param)

    # set inplace to False for all modules
    for module in m.modules():
        if hasattr(module, 'inplace'):
            module.inplace = False

    def transform_input(self_module, inputs):
        input_list = list()
        for t in inputs:
            if isinstance(t, torch.Tensor):
                t = to_outplace_tensor(t)
            input_list.append(t)
        return tuple(input_list)

    m.register_forward_pre_hook(transform_input)

    return m


def main():
    torch.Tensor.add_ = torch.Tensor.add

    # x = MyParameter(torch.randn(4, 4))
    # print(x.my_data.data_ptr())
    # y = MyParameter(torch.randn(4, 4))
    # print(y.my_data.data_ptr())
    import torch.nn.functional as F

    x = torch.randn(4, 4)
    x = to_outplace_tensor(x)

    x = F.relu(x, True)

    exit(0)

    print(x.data_ptr(), x)
    y = torch.randn(4, 4, requires_grad=True)
    y = to_outplace_tensor(y)
    print(y.data_ptr(), y)

    print(x.data_ptr(), x)


if __name__ == '__main__':
    main()