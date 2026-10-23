classdef Linear
    %LINEAR A test model type: y = a + b * x for one input, with a constant
    %standard deviation; it serves values, std, quantiles (a + b * x +
    %(2q - 1) * std, to test the plumbing) and the derivative with respect
    %to its input.
    properties (Constant)
        Type = 'test_linear'
    end
    properties
        A
        B
        Std
        Input
        Output
    end
    methods
        function numbers = save(m)
            numbers = struct('a', m.A, 'b', m.B, 'std', m.Std, 'input', m.Input, ...
                'output', m.Output);
        end
        function out = call(m, inputs, wanted)
            x = double(inputs.(m.Input));
            out = struct();
            for k = 1:numel(wanted)
                w = wanted{k};
                switch w{2}
                    case 'values', out.(w{1}).values = m.A + m.B * x;
                    case 'std', out.(w{1}).std = repmat(m.Std, size(x));
                    case 'quantile'
                        if ~isfield(out, w{1}) || ~isfield(out.(w{1}), 'quantiles')
                            out.(w{1}).quantiles = containers.Map('KeyType', 'double', ...
                                'ValueType', 'any');
                        end
                        q = out.(w{1}).quantiles;          % a handle: filled in place
                        q(w{3}) = m.A + m.B * x + (2 * w{3} - 1) * m.Std;
                    case 'derivative', out.(w{1}).derivatives.(w{3}) = repmat(m.B, size(x));
                    otherwise, error('gamut:error', 'test_linear gives no %s', w{2});
                end
            end
        end
    end
    methods (Static)
        function m = load(numbers)
            m = testmodels.Linear();
            m.A = numbers.a; m.B = numbers.b; m.Std = numbers.std;
            m.Input = numbers.input; m.Output = numbers.output;
        end
    end
end
