classdef Linear
    %LINEAR A test model type: y = a + b * x for one input, with a constant
    %standard deviation; it serves values and std, nothing else.
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
                    otherwise, error('mestra:error', 'test_linear gives values and std only');
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
