function out = evaluate(modelPath, inputs, varargin)
%EVALUATE Evaluates a model file on a table of inputs (spec section 7.4).
%   out = mestra.evaluate(modelPath, inputs)
%   out = mestra.evaluate(modelPath, inputs, 'path', p)
%   out = mestra.evaluate(modelPath, inputs, 'coordinates', C)
%   inputs maps each parameter to values and each label to names (a cell
%   array) from the model file's table, all of one length n.  C (n x nodes
%   x axes) is needed when a model reads geometry the file does not store.
%   Returns the resulting data file open to read; without 'path' it lives
%   in a temporary file removed when it is closed.
p = inputParser;
p.addParameter('path', '');
p.addParameter('coordinates', []);
p.parse(varargin{:});
coordinates = p.Results.coordinates;
m = mestra.open(modelPath);
closeModel = onCleanup(@() m.close());
if ~strcmp(m.kind(), 'model')
    error('mestra:E16', '%s is not a model file', modelPath);
end
params = m.names('parameters'); params = params(:)';
labels = m.names('labels'); labels = labels(:)';
given = fieldnames(inputs)';
if isempty(given)
    error('mestra:E2', 'give the model''s inputs');
end
lengths = cellfun(@(k) numel(inputs.(k)), given);
if any(lengths ~= lengths(1))
    error('mestra:E5', 'every input needs the same number of rows');
end
n = lengths(1);
unknown = setdiff(given, [params labels]);
if ~isempty(unknown)
    error('mestra:E2', '%s is not an input of this model', unknown{1});
end

% The table each model reads: parameters as values, labels as codes.
tbl = struct();
labelNames = struct();
for k = 1:numel(params)
    name = params{k};
    if ~isfield(inputs, name)
        error('mestra:E2', 'the input %s is missing', name);
    end
    d = m.describe(name);
    if strcmp(mestra.internal.field(d, 'dtype', ''), 'int64')
        col = int64(inputs.(name)(:));
    else
        col = double(inputs.(name)(:));
    end
    lo = str2double(d.lower); hi = str2double(d.upper);
    outside = find(col < lo | col > hi, 1);
    if ~isempty(outside)
        warning('mestra:W4', '%s is outside the model''s domain [%g, %g] at row %d', ...
            name, lo, hi, outside);
    end
    tbl.(name) = col;
end
for k = 1:numel(labels)
    name = labels{k};
    if ~isfield(inputs, name)
        error('mestra:E2', 'the input %s is missing', name);
    end
    d = m.describe(name);
    entries = mestra_mex('table', m.Handle, d.category);
    names = cellstr(inputs.(name));
    [known, at] = ismember(names(:), entries(:));
    if ~all(known)
        bad = names(~known);
        error('mestra:E9', '%s: ''%s'' is not in the model''s table', name, bad{1});
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
    statistic = mestra.internal.field(d, 'statistic', '');
    wrt = mestra.internal.field(d, 'with_respect_to', '');
    if strcmp(statistic, 'std')
        req = {d.output, 'std'};
    elseif strcmp(statistic, 'quantile')
        req = {d.output, 'quantile', str2double(d.q)};
    elseif ~isempty(wrt)
        req = {d.output, 'derivative', wrt};
    else
        req = {d.output, 'values'};
    end
    wanted = ask(wanted, d.model, req);
    requests(end + 1, :) = {name, d.model, d.output, req}; %#ok<AGROW>
end
coordinate = struct();
if ~isempty(m.MeshKind)
    coordinate = m.describe('coordinates');
    if ~isempty(mestra.internal.field(coordinate, 'model', ''))
        wanted = ask(wanted, coordinate.model, {coordinate.output, 'values'});
    end
end

% Each model, loaded by its registered type and called once.
outputs = containers.Map('KeyType', 'char', 'ValueType', 'any');
ids = keys(wanted);
for k = 1:numel(ids)
    id = ids{k};
    dm = m.describe(['models/' id]);
    cls = mestra.internal.registry(dm.type);
    if isempty(cls)
        error('mestra:error', ['the model %s is of type ''%s'', whose software is not ' ...
            'registered here (mestra.registerModelType)'], id, dm.type);
    end
    numbers = mestra_mex('model_numbers', m.Handle, id);
    model = feval([cls '.load'], numbers);
    reads = strsplit(strtrim(dm.inputs), ' ');
    in = struct();
    for j = 1:numel(reads)
        if ~isfield(tbl, reads{j})
            error('mestra:E2', 'the model %s reads %s, which was not given', id, reads{j});
        end
        in.(reads{j}) = tbl.(reads{j});
    end
    outputs(id) = model.call(in, wanted(id));
end

% The data file.
outPath = p.Results.path;
temporary = isempty(outPath);
if temporary
    outPath = [tempname '.mes'];
end
w = mestra.Study(mestra_mex('evaluate_begin', m.Handle, outPath), outPath, true, ...
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
out = mestra.open(outPath);
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
        error('mestra:error', 'the model %s gave no output %s', id, output);
    end
    record = got.(output);
    values = [];
    switch req{2}
        case 'values'
            values = mestra.internal.field(record, 'values', []);
        case 'std'
            values = mestra.internal.field(record, 'std', []);
        case 'quantile'
            q = mestra.internal.field(record, 'quantiles', []);
            if isa(q, 'containers.Map') && isKey(q, req{3}), values = q(req{3}); end
        case 'derivative'
            dv = mestra.internal.field(record, 'derivatives', struct());
            values = mestra.internal.field(dv, req{3}, []);
    end
    if isempty(values)
        error('mestra:error', 'the model %s gave no %s for %s', id, req{2}, output);
    end
    if any(strcmp(scalars, name))
        columns.(name) = double(values(:));
    else
        fields.(name) = reshape(double(values), n, []);
    end
end
points = {};
if ~isempty(m.MeshKind) && strcmp(m.Per, 'run')
    if ~isempty(mestra.internal.field(coordinate, 'model', ''))
        got = outputs(coordinate.model);
        pts = got.(coordinate.output).values;
    elseif ~isempty(coordinates)
        pts = double(coordinates);
    else
        error('mestra:E2', 'this model file''s geometry changes per run; give coordinates');
    end
    points = cell(1, n);
    for i = 1:n
        points{i} = reshape(pts(i, :, :), size(pts, 2), size(pts, 3));
    end
end
w.addRuns(columns, 'fields', fields, 'points', points);
end

function wanted = ask(wanted, id, req)
if isKey(wanted, id)
    wanted(id) = [wanted(id) {req}];
else
    wanted(id) = {req};
end
end
