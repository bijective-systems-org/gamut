classdef Nearest
    %NEAREST The built-in model: for each input row, the outputs of the
    %closest stored point (spec section 7.5).  Evaluated by the core, so
    %every language gets the same answers.
    %   m = gamut.Nearest(columns, lower, upper, x, outputs)
    %   m = gamut.Nearest(columns, lower, upper, x, outputs, widths)
    %   columns: cell of input names, parameters and arrays; lower, upper:
    %   bounds per column; widths: each column's number of values (1 for a
    %   parameter, an array's length; all 1 when left out); x: points x
    %   values, each point's inputs side by side in the order of columns;
    %   outputs: struct of arrays, points first.

    properties (Constant)
        Type = 'nearest'
    end

    properties (SetAccess = private)
        Columns
        Lower
        Upper
        X
        Outputs
        Widths
    end

    methods
        function m = Nearest(columns, lower, upper, x, outputs, widths)
            m.Columns = cellstr(columns);
            m.Columns = m.Columns(:)';
            m.Lower = double(lower(:)');
            m.Upper = double(upper(:)');
            % x is points x columns as given, so the core refuses another
            % orientation; one column of one value each may be a vector of
            % points (an array's points are rows of x, even one).
            if nargin >= 6 && ~isempty(widths)
                m.Widths = int64(widths(:)');
            end
            m.X = double(x);
            if isvector(m.X) && isscalar(m.Columns) && (isempty(m.Widths) || m.Widths == 1)
                m.X = m.X(:);
            end
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
            if ~isempty(m.Widths), numbers.widths = m.Widths; end
        end

        function out = call(m, inputs, wanted)
            % A parameter as a column; an array as rows x length, which the
            % gateway gives the core row by row.
            cols = cell(1, numel(m.Columns));
            widths = ones(1, numel(m.Columns));
            if ~isempty(m.Widths), widths = double(m.Widths); end
            rows = 0;
            for j = 1:numel(m.Columns)
                cols{j} = double(inputs.(m.Columns{j}));
                if widths(j) == 1, cols{j} = cols{j}(:); end
                if j == 1, rows = size(cols{j}, 1); end
            end
            out = struct();
            for k = 1:numel(wanted)
                w = wanted{k};
                if ~strcmp(w{2}, 'values')
                    error('gamut:error', 'nearest gives values only, not %s', w{2});
                end
                v = gamut_mex('nearest_call', m.save(), m.Columns, cols, w{1}, rows);
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
            widths = [];
            if isfield(numbers, 'widths'), widths = numbers.widths; end
            m = gamut.Nearest(numbers.columns, numbers.lower, numbers.upper, numbers.x, ...
                numbers.outputs, widths);
        end
    end
end
