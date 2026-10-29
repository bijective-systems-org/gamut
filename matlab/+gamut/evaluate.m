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
coordinates = p.Results.coordinates;
m = gamut.open(modelPath);
closeModel = onCleanup(@() m.close());
if ~strcmp(m.kind(), 'model')
    error('gamut:E16', '%s is not a model file', modelPath);
end
params = m.names('parameters'); params = params(:)';
labels = m.names('labels'); labels = labels(:)';
given = fieldnames(inputs)';
if isempty(given)
    error('gamut:E2', 'give the model''s inputs');
end
lengths = cellfun(@(k) numel(inputs.(k)), given);
if any(lengths ~= lengths(1))
    error('gamut:E5', 'every input needs the same number of rows');
end
n = lengths(1);
unknown = setdiff(given, [params labels]);
if ~isempty(unknown)
    error('gamut:E2', '%s is not an input of this model', unknown{1});
end

% The table each model reads: parameters as values, labels as codes.
tbl = struct();
labelNames = struct();
for k = 1:numel(params)
    name = params{k};
    if ~isfield(inputs, name)
        error('gamut:E2', 'the input %s is missing', name);
    end
    d = m.describe(name);
    if strcmp(gamut.internal.field(d, 'dtype', ''), 'int64')
        % Whole numbers in range only: int64() would round or saturate silently.
        v = inputs.(name)(:);
        if ~isnumeric(v) || ~isreal(v) || issparse(v) || ...
                (isfloat(v) && any(v ~= fix(v) | ~isfinite(v) | v >= 2^63 | v < -2^63)) || ...
                (isa(v, 'uint64') && any(v > uint64(intmax('int64'))))
            error('gamut:E4', '%s is int64 and takes whole numbers in its range', name);
        end
        col = int64(v);
    else
        col = exactDouble(inputs.(name)(:), name);
    end
    lo = str2double(declared(d, 'lower', name)); hi = str2double(declared(d, 'upper', name));
    outside = find(col < lo | col > hi, 1);
    if ~isempty(outside)
        warning('gamut:W4', '%s is outside the model''s domain [%g, %g] at row %d', ...
            name, lo, hi, outside);
    end
    tbl.(name) = col;
end
for k = 1:numel(labels)
    name = labels{k};
    if ~isfield(inputs, name)
        error('gamut:E2', 'the input %s is missing', name);
    end
    d = m.describe(name);
    entries = gamut_mex('table', m.Handle, declared(d, 'category', name));
    names = cellstr(inputs.(name));
    [known, at] = ismember(names(:), entries(:));
    if ~all(known)
        bad = names(~known);
        error('gamut:E9', '%s: ''%s'' is not in the model''s table', name, bad{1});
    end
    tbl.(name) = int64(at(:) - 1);
    labelNames.(name) = names(:);
end
if ~isempty(coordinates)
    tbl.coordinates = double(coordinates);
elseif ~isempty(m.MeshKind) && strcmp(m.Per, 'fixed')
    pts = m.getPoints();
    tbl.coordinates = repmat(reshape(pts, [1 size(pts)]), [n 1 1]);
end

% What each model is asked for.
scalars = m.names('scalars');
nodeFields = m.names('node_fields');
cellFields = m.names('cell_fields');
results = [scalars(:); nodeFields(:); cellFields(:)];
wanted = containers.Map('KeyType', 'char', 'ValueType', 'any');
requests = cell(0, 4);
for k = 1:numel(results)
    name = results{k};
    d = m.describe(name);
    statistic = gamut.internal.field(d, 'statistic', '');
    wrt = gamut.internal.field(d, 'with_respect_to', '');
    output = declared(d, 'output', name);
    modelId = declared(d, 'model', name);
    if strcmp(statistic, 'std')
        req = {output, 'std'};
    elseif strcmp(statistic, 'quantile')
        req = {output, 'quantile', str2double(declared(d, 'q', name))};
    elseif ~isempty(wrt)
        req = {output, 'derivative', wrt};
    else
        req = {output, 'values'};
    end
    wanted = ask(wanted, modelId, req);
    requests(end + 1, :) = {name, modelId, output, req}; %#ok<AGROW>
end
coordinate = struct();
if ~isempty(m.MeshKind)
    coordinate = m.describe('coordinates');
    if ~isempty(gamut.internal.field(coordinate, 'model', ''))
        wanted = ask(wanted, coordinate.model, {declared(coordinate, 'output', 'coordinates'), ...
            'values'});
    end
end

% Each model, loaded by its registered type and called once.
outputs = containers.Map('KeyType', 'char', 'ValueType', 'any');
ids = keys(wanted);
for k = 1:numel(ids)
    id = ids{k};
    dm = m.describe(['models/' id]);
    modelType = declared(dm, 'type', ['models/' id]);
    cls = gamut.internal.registry(modelType);
    if isempty(cls)
        error('gamut:error', ['the model %s is of type ''%s'', whose software is not ' ...
            'registered here (gamut.registerModelType)'], id, modelType);
    end
    numbers = m.modelNumbers(id);
    model = feval([cls '.load'], numbers);
    reads = strsplit(strtrim(declared(dm, 'inputs', ['models/' id])), ' ');
    in = struct();
    for j = 1:numel(reads)
        if ~isfield(tbl, reads{j})
            error('gamut:E2', 'the model %s reads %s, which was not given', id, reads{j});
        end
        in.(reads{j}) = tbl.(reads{j});
    end
    outputs(id) = model.call(in, wanted(id));
end

% The data file.
outPath = p.Results.path;
temporary = isempty(outPath);
if temporary
    outPath = [tempname '.gamut'];
end
w = gamut.Study(gamut_mex('evaluate_begin', m.Handle, outPath), outPath, true, ...
    m.MeshKind, m.Per);
try
    write(w, m, n, params, labels, tbl, labelNames, scalars, requests, outputs, coordinate, ...
        coordinates);
catch err
    % A failed evaluation leaves no file behind.
    w.abandon(true);
    rethrow(err);
end
w.close();
out = gamut.open(outPath);
out.RemoveOnClose = temporary;
end

function write(w, m, n, params, labels, tbl, labelNames, scalars, requests, outputs, ...
    coordinate, coordinates)
columns = struct();
for k = 1:numel(params), columns.(params{k}) = tbl.(params{k}); end
for k = 1:numel(labels), columns.(labels{k}) = labelNames.(labels{k}); end
fields = struct();
for k = 1:size(requests, 1)
    [name, id, output, req] = requests{k, :};
    got = outputs(id);
    if ~isfield(got, output)
        error('gamut:error', 'the model %s gave no output %s', id, output);
    end
    record = got.(output);
    values = [];
    switch req{2}
        case 'values'
            values = gamut.internal.field(record, 'values', []);
        case 'std'
            values = gamut.internal.field(record, 'std', []);
        case 'quantile'
            q = gamut.internal.field(record, 'quantiles', []);
            if isa(q, 'containers.Map') && isKey(q, req{3}), values = q(req{3}); end
        case 'derivative'
            dv = gamut.internal.field(record, 'derivatives', struct());
            values = gamut.internal.field(dv, req{3}, []);
    end
    if isempty(values)
        error('gamut:error', 'the model %s gave no %s for %s', id, req{2}, output);
    end
    if any(strcmp(scalars, name))
        columns.(name) = exactDouble(values(:), name);
    else
        fields.(name) = reshape(exactDouble(values, name), n, []);
    end
end
points = {};
if ~isempty(m.MeshKind) && strcmp(m.Per, 'run')
    if ~isempty(gamut.internal.field(coordinate, 'model', ''))
        got = outputs(coordinate.model);
        pts = got.(coordinate.output).values;
    elseif ~isempty(coordinates)
        pts = exactDouble(coordinates, 'coordinates');
    else
        error('gamut:E2', 'this model file''s geometry changes per run; give coordinates');
    end
    points = cell(1, n);
    for i = 1:n
        points{i} = reshape(pts(i, :, :), size(pts, 2), size(pts, 3));
    end
end
w.addRuns(columns, 'fields', fields, 'points', points);
end

function v = declared(d, key, name)
% An attribute evaluating relies on: one the model file lacks is refused,
% rather than a missing field.
if ~isfield(d, key)
    error('gamut:error', '%s has no %s; gamut validate says what the file breaks', name, key);
end
v = d.(key);
end

function wanted = ask(wanted, id, req)
if isKey(wanted, id)
    wanted(id) = [wanted(id) {req}];
else
    wanted(id) = {req};
end
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
