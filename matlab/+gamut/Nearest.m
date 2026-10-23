classdef Nearest
    %NEAREST The built-in model: for each input row, the outputs of the
    %closest stored point (spec section 7.5).  Evaluated by the core, so
    %every language gets the same answers.
    %   m = gamut.Nearest(columns, lower, upper, x, outputs)
    %   columns: cell of input names; lower, upper: bounds per column;
    %   x: points x columns; outputs: struct of arrays, points first.

    properties (Constant)
        Type = 'nearest'
    end

    properties (SetAccess = private)
        Columns
        Lower
        Upper
        X
        Outputs
    end

    methods
        function m = Nearest(columns, lower, upper, x, outputs)
            m.Columns = cellstr(columns);
            m.Columns = m.Columns(:)';
            m.Lower = double(lower(:)');
            m.Upper = double(upper(:)');
            m.X = reshape(double(x), [], numel(m.Columns));
            m.Outputs = outputs;
            names = fieldnames(outputs);
            for k = 1:numel(names)
                m.Outputs.(names{k}) = double(outputs.(names{k}));
            end
            gamut_mex('nearest_check', m.save());
        end

        function numbers = save(m)
            numbers = struct('columns', {m.Columns}, 'lower', m.Lower, 'upper', m.Upper, ...
                'x', m.X, 'outputs', m.Outputs);
        end

        function out = call(m, inputs, wanted)
            cols = cell(1, numel(m.Columns));
            for j = 1:numel(m.Columns)
                cols{j} = double(inputs.(m.Columns{j}));
                cols{j} = cols{j}(:);
            end
            out = struct();
            for k = 1:numel(wanted)
                w = wanted{k};
                if ~strcmp(w{2}, 'values')
                    error('gamut:error', 'nearest gives values only, not %s', w{2});
                end
                v = gamut_mex('nearest_call', m.save(), m.Columns, cols, w{1});
                shape = size(m.Outputs.(w{1}));
                if numel(shape) > 2 || shape(2) > 1
                    v = reshape(v, [size(v, 1), shape(2:end)]);
                end
                out.(w{1}).values = v;
            end
        end
    end

    methods (Static)
        function m = load(numbers)
            % Numbers from a file are checked before any is looked up: a
            % damaged or foreign file may lack one (E17).
            gamut_mex('nearest_check', numbers);
            m = gamut.Nearest(numbers.columns, numbers.lower, numbers.upper, numbers.x, ...
                numbers.outputs);
        end
    end
end
