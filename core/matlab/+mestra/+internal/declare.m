function declare(h, o)
%DECLARE Declarations shared by mestra.create and mestra.createModel.
if isfield(o, 'compression') && ~o.compression
    mestra_mex('set_compression', h, 0, 0);
end
attrs = {'title', 'license', 'references', 'source'};
for k = 1:numel(attrs)
    if isfield(o, attrs{k}) && ~isempty(o.(attrs{k}))
        mestra_mex('set_attribute', h, attrs{k}, o.(attrs{k}));
    end
end
if isfield(o, 'trainedOn') && ~isempty(o.trainedOn)
    mestra_mex('set_attribute', h, 'trained_on', strjoin(cellstr(o.trainedOn), ' '));
end
names = fieldnames(o.labels);
for k = 1:numel(names)
    v = o.labels.(names{k});
    if ischar(v) || isstring(v)
        v = struct('role', char(v));
    end
    mestra_mex('declare_label', h, names{k}, mestra.internal.field(v, 'role', 'categorical'), ...
        mestra.internal.field(v, 'categories', {}));
end
names = fieldnames(o.parameters);
for k = 1:numel(names)
    v = mestra.internal.spec(o.parameters.(names{k}));
    has = isfield(v, 'lower');
    mestra_mex('declare_parameter', h, names{k}, mestra.internal.field(v, 'role', 'design'), ...
        v.units, mestra.internal.dtype(mestra.internal.field(v, 'dtype', '')), double(has), ...
        mestra.internal.field(v, 'lower', 0), mestra.internal.field(v, 'upper', 0), ...
        mestra.internal.field(v, 'runGroup', ''));
end
if ~isempty(o.coordinates)
    c = o.coordinates;
    mestra_mex('declare_coordinates', h, c.units, ...
        mestra.internal.dtype(mestra.internal.field(c, 'precision', '')), ...
        mestra.internal.field(c, 'axes', 3), mestra.internal.field(c, 'model', ''), ...
        mestra.internal.field(c, 'output', ''));
end
names = fieldnames(o.meshLabels);
for k = 1:numel(names)
    v = o.meshLabels.(names{k});
    mestra_mex('declare_mesh_label', h, names{k}, mestra.internal.field(v, 'at', 'cell'), ...
        mestra.internal.field(v, 'categories', {}));
end
groups = {'scalars', 'fields'};
for g = 1:2
    names = fieldnames(o.(groups{g}));
    for k = 1:numel(names)
        v = mestra.internal.spec(o.(groups{g}).(names{k}));
        if g == 1, where = 'scalar'; else, where = mestra.internal.field(v, 'at', 'node'); end
        precision = mestra.internal.field(o.precision, names{k}, mestra.internal.field(v, 'precision', ''));
        q = mestra.internal.field(v, 'q', []);
        hasQ = ~isempty(q);
        if ~hasQ, q = 0; end
        mestra_mex('declare_result', h, names{k}, where, v.units, mestra.internal.dtype(precision), ...
            mestra.internal.field(v, 'of', ''), mestra.internal.field(v, 'statistic', ''), ...
            double(hasQ), double(q), mestra.internal.field(v, 'method', ''), ...
            mestra.internal.field(v, 'withRespectTo', ''), mestra.internal.field(v, 'axis', ''), ...
            mestra.internal.field(v, 'vector', ''), mestra.internal.field(v, 'roundBits', -1), ...
            mestra.internal.field(v, 'model', ''), mestra.internal.field(v, 'output', ''));
    end
end
if isfield(o, 'generalisationGroup') && ~isempty(o.generalisationGroup)
    mestra_mex('set_generalisation_group', h, o.generalisationGroup);
end
names = fieldnames(o.constants);
for k = 1:numel(names)
    c = o.constants.(names{k});
    mestra_mex('set_constant', h, names{k}, c{2}, c{1});
end
end
