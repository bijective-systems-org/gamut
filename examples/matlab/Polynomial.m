classdef Polynomial
    %POLYNOMIAL A polynomial in one input, highest power first, as polyfit
    %   gives it: the MATLAB class of the model type example.polynomial,
    %   whose Python class is in examples/07_models.py.

    properties (Constant)
        Type = 'example.polynomial'
    end

    properties
        Coefficients
    end

    methods
        function m = Polynomial(coefficients)
            m.Coefficients = coefficients;
        end

        function numbers = save(m)
            numbers = struct('coefficients', m.Coefficients);
        end

        function out = call(m, inputs, wanted)
            names = fieldnames(inputs);
            x = inputs.(names{1});
            out = struct();
            for k = 1:numel(wanted)
                out.(wanted{k}{1}).values = polyval(m.Coefficients, x);
            end
        end
    end

    methods (Static)
        function m = load(numbers)
            m = Polynomial(numbers.coefficients);
        end
    end
end
