function declare(h, o)
%DECLARE Declarations shared by gamut.create and gamut.createModel.
if isfield(o, 'compression') && ~o.compression
    gamut_mex('set_compression', h, 0, 0);
end
attrs = {'title', 'license', 'references', 'source'};
for k = 1:numel(attrs)
    if isfield(o, attrs{k}) && ~isempty(o.(attrs{k}))
        gamut_mex('set_attribute', h, attrs{k}, o.(attrs{k}));
    end
end
if isfield(o, 'trainedOn') && ~isempty(o.trainedOn)
    gamut_mex('set_attribute', h, 'trained_on', strjoin(cellstr(o.trainedOn), ' '));
end
names = fieldnames(o.labels);
for k = 1:numel(names)
    v = o.labels.(names{k});
    if ischar(v) || isstring(v)
        v = struct('role', char(v));
    end
    gamut_mex('declare_label', h, names{k}, gamut.internal.field(v, 'role', 'categorical'), ...
        gamut.internal.field(v, 'categories', {}));
end
names = fieldnames(o.parameters);
for k = 1:numel(names)
    v = gamut.internal.spec(o.parameters.(names{k}));
    has = isfield(v, 'lower') || isfield(v, 'upper');
    gamut_mex('declare_parameter', h, names{k}, gamut.internal.field(v, 'role', 'design'), ...
        v.units, gamut.internal.dtype(gamut.internal.field(v, 'dtype', '')), double(has), ...
        gamut.internal.field(v, 'lower', NaN), gamut.internal.field(v, 'upper', NaN), ...
        gamut.internal.field(v, 'runGroup', ''));
end
if ~isempty(o.coordinates)
    c = o.coordinates;
    gamut_mex('declare_coordinates', h, c.units, ...
        gamut.internal.dtype(gamut.internal.field(c, 'precision', '')), ...
        gamut.internal.field(c, 'axes', 3), gamut.internal.field(c, 'model', ''), ...
        gamut.internal.field(c, 'output', ''));
end
names = fieldnames(o.meshLabels);
for k = 1:numel(names)
    v = o.meshLabels.(names{k});
    gamut_mex('declare_mesh_label', h, names{k}, gamut.internal.field(v, 'at', 'cell'), ...
        gamut.internal.field(v, 'categories', {}));
end
groups = {'scalars', 'fields'};
for g = 1:2
    names = fieldnames(o.(groups{g}));
    for k = 1:numel(names)
        v = gamut.internal.spec(o.(groups{g}).(names{k}));
        if g == 1, where = 'scalar'; else, where = gamut.internal.field(v, 'at', 'node'); end
        precision = gamut.internal.field(o.precision, names{k}, gamut.internal.field(v, 'precision', ''));
        q = gamut.internal.field(v, 'q', []);
        hasQ = ~isempty(q);
        if ~hasQ, q = 0; end
        gamut_mex('declare_result', h, names{k}, where, v.units, gamut.internal.dtype(precision), ...
            gamut.internal.field(v, 'of', ''), gamut.internal.field(v, 'statistic', ''), ...
            double(hasQ), double(q), gamut.internal.field(v, 'method', ''), ...
            gamut.internal.field(v, 'withRespectTo', ''), gamut.internal.field(v, 'axis', ''), ...
            gamut.internal.field(v, 'vector', ''), gamut.internal.field(v, 'roundBits', -1), ...
            gamut.internal.field(v, 'model', ''), gamut.internal.field(v, 'output', ''));
    end
end
if isfield(o, 'generalisationGroup') && ~isempty(o.generalisationGroup)
    gamut_mex('set_generalisation_group', h, o.generalisationGroup);
end
names = fieldnames(o.constants);
for k = 1:numel(names)
    c = o.constants.(names{k});
    gamut_mex('set_constant', h, names{k}, c{2}, c{1});
end
end
