function out = evaluate(modelPath, inputs, varargin)
%EVALUATE Evaluates a model file on a table of inputs (spec section 7.4).
%   out = gamut.evaluate(modelPath, inputs)
%   out = gamut.evaluate(modelPath, inputs, 'path', p)
%   out = gamut.evaluate(modelPath, inputs, 'coordinates', C)
%   inputs maps each parameter to values and each label to names (a cell
%   array) from the model file's table, all of one length n.  C (n x nodes
%   x axes) is needed when a model reads geometry the file does not store.
%   Returns the resulting data file open to read; without 'path' it lives
%   in a temporary file removed when it is closed.  An input outside a
%   parameter's bounds is evaluated, with a warning (gamut:W4), and
%   out.outside(name) says how far each row lies outside.
p = inputParser;
p.addParameter('path', '');
p.addParameter('coordinates', []);
p.parse(varargin{:});
m = gamut.open(modelPath);
closeModel = onCleanup(@() m.close());
labels = m.names('labels');
params = m.names('parameters');
given = fieldnames(inputs)';
n = 0;
if ~isempty(given), n = numel(inputs.(given{1})); end
outPath = p.Results.path;
temporary = isempty(outPath);
if temporary
    outPath = [tempname '.gamut'];
end

% The core checks the inputs, runs the built-in models and writes the
% answer; this layer converts values and calls the registered types.
ev = gamut_mex('evaluation_begin', m.Handle, n, outPath);
freeEvaluation = onCleanup(@() gamut_mex('evaluation_free', ev));
for k = 1:numel(given)
    name = given{k};
    if any(strcmp(labels, name))
        gamut_mex('evaluation_names', ev, name, cellstr(inputs.(name)));
    elseif ~any(strcmp(params, name))   % the core refuses the name (E2) before its values
        gamut_mex('evaluation_values', ev, name, []);
    elseif strcmp(gamut.internal.field(m.describe(name), 'dtype', ''), 'int64')
        gamut_mex('evaluation_values', ev, name, int64Exactly(inputs.(name)(:), name));
    else
        gamut_mex('evaluation_values', ev, name, exactDouble(inputs.(name)(:), name));
    end
end
if ~isempty(p.Results.coordinates)
    gamut_mex('evaluation_coordinates', ev, exactDouble(p.Results.coordinates, 'coordinates'));
end
[found, models] = gamut_mex('evaluation_ready', ev);
for k = 1:numel(found)
    warning('gamut:W4', '%s', regexprep(found{k}, '^W4: ', ''));
end
for k = 1:numel(models)
    run(m, ev, models{k});
end
gamut_mex('evaluation_finish', ev);
out = gamut.open(outPath);
out.RemoveOnClose = temporary;
end

function run(m, ev, id)
% Calls one model of a registered type with what it reads, and gives the
% evaluation each answer it is asked for.
dm = m.describe(['models/' id]);
cls = gamut.internal.registry(dm.type);
if isempty(cls)
    error('gamut:error', ['the model %s is of type ''%s'', whose software is not ' ...
        'registered here (gamut.registerModelType)'], id, dm.type);
end
model = feval([cls '.load'], m.modelNumbers(id));
reads = strsplit(strtrim(dm.inputs), ' ');
in = struct();
for j = 1:numel(reads)
    in.(reads{j}) = gamut_mex('evaluation_input', ev, reads{j});
end
[outputs, kinds, keys] = gamut_mex('evaluation_requests', ev, id);
wanted = cell(1, numel(outputs));
for j = 1:numel(outputs)
    switch kinds{j}
        case 'quantile', wanted{j} = {outputs{j}, 'quantile', str2double(keys{j})};
        case 'derivative', wanted{j} = {outputs{j}, 'derivative', keys{j}};
        otherwise, wanted{j} = {outputs{j}, kinds{j}};
    end
end
got = model.call(in, wanted);
for j = 1:numel(outputs)
    o = outputs{j};
    if ~isfield(got, o)
        error('gamut:error', 'the model %s gave no output %s', id, o);
    end
    record = got.(o);
    values = [];
    switch kinds{j}
        case 'values'
            values = gamut.internal.field(record, 'values', []);
        case 'std'
            values = gamut.internal.field(record, 'std', []);
        case 'quantile'
            q = gamut.internal.field(record, 'quantiles', []);
            if isa(q, 'containers.Map') && isKey(q, wanted{j}{3}), values = q(wanted{j}{3}); end
        case 'derivative'
            dv = gamut.internal.field(record, 'derivatives', struct());
            values = gamut.internal.field(dv, keys{j}, []);
    end
    if isempty(values)
        error('gamut:error', 'the model %s gave no %s for %s', id, kinds{j}, o);
    end
    gamut_mex('evaluation_answer', ev, id, o, kinds{j}, keys{j}, values);   % converted by the core
end
end

function v = int64Exactly(v, name)
% Whole numbers in range only: int64() would round or saturate silently.
if ~isnumeric(v) || ~isreal(v) || issparse(v) || ...
        (isfloat(v) && any(v ~= fix(v) | ~isfinite(v) | v >= 2^63 | v < -2^63)) || ...
        (isa(v, 'uint64') && any(v > uint64(intmax('int64'))))
    error('gamut:E4', '%s is int64 and takes whole numbers in its range', name);
end
v = int64(v);
end

function v = exactDouble(v, name)
%EXACTDOUBLE double(v), refusing an integer that double() would round (past
%   2^53) as the core refuses one.
if isa(v, 'int64') || isa(v, 'uint64')
    d = double(v);
    top = 2^63; if isa(v, 'uint64'), top = 2^64; end   % the first double past the class
    if any(d(:) >= top | cast(d(:), class(v)) ~= v(:))
        error('gamut:E4', '%s: an integer past 2^53 is not exact as a float64', name);
    end
end
v = double(v);
end
