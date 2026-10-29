classdef Study < handle
    %STUDY A study file open to write (gamut.create) or to read (gamut.open).
    %   Positions (rows, nodes, cells) are 1-based here, as MATLAB indexes;
    %   arrays come back with the logical axes (row, node) in that order.

    properties (SetAccess = private)
        Path
    end
    properties (Hidden)
        Handle
        Writing
        MeshKind
        Per
        Group
        Axes = 3
        RemoveOnClose = false   % an evaluated file in a temporary place
    end

    methods
        function s = Study(handle, path, writing, meshKind, per)
            s.Handle = handle;
            s.Path = path;
            s.Writing = writing;
            s.MeshKind = meshKind;
            s.Per = per;
            if ~writing
                s.MeshKind = s.info1('mesh_kind');
                s.Per = s.info1('per');
            end
            if startsWith(s.Per, 'group:')
                s.Group = extractAfter(s.Per, 'group:');
            else
                s.Group = '';
            end
        end

        function close(s)
            %CLOSE Finishes the file.  A refused close (a shared mesh never
            %   set, a model file without a model) keeps it open to fix and
            %   close again.
            if ~isempty(s.Handle)
                gamut_mex('close', s.Handle);
                s.Handle = [];
                if s.RemoveOnClose && isfile(s.Path)
                    delete(s.Path);
                end
            end
        end

        function delete(s)
            try
                s.close();
            catch
                s.abandon(false);
            end
        end

        % --- writing -------------------------------------------------------

        function setMesh(s, points, cells, labels, nNodes)
            %SETMESH The mesh: points (nodes x axes) when fixed, cells as
            %   {types, offsets, connectivity} (0-based node numbers, as VTK),
            %   fixed mesh labels as a struct; nNodes when points come per run.
            if nargin < 3, cells = {}; end
            if nargin < 4, labels = struct(); end
            gamut_mex('geometry_begin', s.Handle);
            if isempty(points)
                gamut_mex('geometry_points', s.Handle, [], nNodes, s.Axes);
            else
                gamut_mex('geometry_points', s.Handle, points);
            end
            s.stageCells(cells, labels);
            gamut_mex('set_mesh', s.Handle);
        end

        function id = addRun(s, values, varargin)
            %ADDRUN Adds one run: values is a struct of parameters, label names
            %   and scalars; 'fields', 'points', 'cells', 'meshLabels' optional.
            p = inputParser;
            p.addParameter('fields', struct());
            p.addParameter('points', []);
            p.addParameter('cells', {});
            p.addParameter('meshLabels', struct());
            p.parse(varargin{:});
            names = fieldnames(values);
            columns = struct();
            for k = 1:numel(names)
                v = values.(names{k});
                if ischar(v) || isstring(v), v = {char(v)}; end
                columns.(names{k}) = v;
            end
            fields = p.Results.fields;
            fn = fieldnames(fields);
            for k = 1:numel(fn)
                f = fields.(fn{k});
                if ~strcmp(s.MeshKind, 'changing'), f = reshape(f, 1, []); end
                fields.(fn{k}) = f;
            end
            pts = {};
            if ~isempty(p.Results.points), pts = {p.Results.points}; end
            cells = {};
            if ~isempty(p.Results.cells), cells = {p.Results.cells}; end
            id = s.commit(1, columns, fields, pts, cells, {p.Results.meshLabels});
        end

        function ids = addRuns(s, columns, varargin)
            %ADDRUNS Adds many runs: columns maps each name to one value per run,
            %   as a struct of columns or a table (readtable's) does, with a
            %   label as names (text or categorical); 'fields' rows x sites.
            p = inputParser;
            p.addParameter('fields', struct());
            p.addParameter('points', {});
            p.addParameter('cells', {});
            p.addParameter('meshLabels', {});
            p.parse(varargin{:});
            if istable(columns), columns = table2struct(columns, 'ToScalar', true); end
            names = fieldnames(columns);
            n = numel(columns.(names{1}));
            ids = s.commit(n, columns, p.Results.fields, p.Results.points, p.Results.cells, ...
                p.Results.meshLabels);
        end

        function setNote(s, key, value)
            gamut_mex('set_note', s.Handle, key, value);
        end

        function addModel(s, id, model, inputs, repr)
            %ADDMODEL Adds a model to a model file: its id, the model (an
            %   object of a registered type, or gamut.Nearest) and the
            %   inputs it reads (parameters, labels, 'coordinates').
            if nargin < 5, repr = ''; end
            gamut_mex('add_model', s.Handle, id, model.Type, cellstr(inputs), model.save(), repr);
        end

        % --- reading -------------------------------------------------------

        function v = kind(s), v = s.info1('kind'); end
        function v = type(s), v = s.info1('type'); end
        function v = addons(s), v = gamut_mex('info', s.Handle, 'addons'); end
        function v = rowCount(s), v = str2double(s.info1('row_count')); end

        function v = names(s, group)
            v = gamut_mex('names', s.Handle, group);
        end

        function d = describe(s, name)
            %DESCRIBE A concept's attributes as a struct of text; with no name
            %   the file's own (writer, created, file_id, title, ...).
            if nargin < 2, name = ''; end
            [k, v] = gamut_mex('describe', s.Handle, name);
            d = struct();
            for i = 1:numel(k)
                d.(k{i}) = v{i};
            end
        end

        function v = modelNumbers(s, id)
            %MODELNUMBERS A model's stored numbers (spec section 12) as a
            %   struct, as its save gave them; its type need not be registered.
            v = gamut_mex('model_numbers', s.Handle, id);
        end

        function v = getRowIds(s, rows)
            if nargin < 2, rows = ':'; end
            v = gamut_mex('read', s.Handle, 'row', s.pos(rows), ':', 4);
        end

        function v = getParameter(s, name, varargin)
            o = s.opts(varargin);
            code = 6;
            if strcmp(gamut.internal.field(s.describe(name), 'dtype', ''), 'int64'), code = 4; end
            v = gamut_mex('read', s.Handle, name, s.pos(o.rows), ':', code);
        end

        function v = outside(s, name, varargin)
            %OUTSIDE How far each row's value of the parameter NAME lies
            %   outside the bounds the file declares for it, in its units: 0
            %   inside or on a bound, value - lower (negative) below, value -
            %   upper (positive) above, NaN where the value is missing.  A
            %   parameter without bounds is refused.  'rows' selects (1-based).
            %   The answer of gamut.evaluate keeps the model's bounds, so this
            %   says which of its rows lie outside the range the model was
            %   fitted on, and how far.
            o = s.opts(varargin);
            v = gamut_mex('outside', s.Handle, name, s.pos(o.rows));
        end

        function v = getLabel(s, name, varargin)
            o = s.opts(varargin);
            v = gamut_mex('label_names', s.Handle, name, s.pos(o.rows));
        end

        function v = getScalar(s, name, varargin)
            o = s.opts(varargin);
            v = gamut_mex('read', s.Handle, name, s.pos(o.rows), ':', s.resultCode(name));
        end

        function v = getConstant(s, name)
            d = s.describe(name);
            if strcmp(d.dtype, 'int64')
                v = gamut_mex('read', s.Handle, name, ':', ':', 4);
            else
                v = gamut_mex('read', s.Handle, name, ':', ':', 6);
            end
        end

        function v = getField(s, name, varargin)
            %GETFIELD A field: 'rows', 'nodes' or 'cells' select (1-based);
            %   rows x sites on a shared mesh, one row's values on a changing one.
            o = s.opts(varargin);
            sites = o.nodes;
            if ischar(sites), sites = o.cells; end
            if strcmp(s.MeshKind, 'changing') && (ischar(o.rows) || numel(o.rows) ~= 1)
                error('gamut:usage', ['%s: a changing mesh is read one row at a time; ' ...
                    'reads across rows need a shared mesh'], name);
            end
            v = gamut_mex('read', s.Handle, name, s.pos(o.rows), s.pos(sites), s.resultCode(name));
            if strcmp(s.MeshKind, 'changing'), v = v(:); end
        end

        function v = getPoints(s, row)
            if nargin < 2, row = ':'; end
            if ischar(row) && ~any(strcmp(s.Per, {'fixed', ''}))
                error('gamut:usage', 'this mesh''s geometry changes; give the row');
            end
            code = 6;
            if strcmp(gamut.internal.field(s.describe('coordinates'), 'dtype', ''), 'float32'), code = 5; end
            v = gamut_mex('read', s.Handle, 'coordinates', s.pos(row), ':', code);
            if ~ischar(row) && strcmp(s.MeshKind, 'shared')
                v = reshape(v(1, :, :), size(v, 2), size(v, 3));
            end
        end

        function [types, offsets, connectivity] = getCells(s, row)
            if nargin < 2, row = ':'; end
            types = gamut_mex('read', s.Handle, 'cells/types', s.pos(row), ':', 1);
            offsets = gamut_mex('read', s.Handle, 'cells/offsets', s.pos(row), ':', 4);
            connectivity = gamut_mex('read', s.Handle, 'cells/connectivity', s.pos(row), ':', 4);
        end

        function v = getMeshLabel(s, name, row)
            if nargin < 3, row = ':'; end
            v = gamut_mex('read', s.Handle, name, s.pos(row), ':', 4);
        end

        function v = categories(s, name)
            %CATEGORIES The category table of a label or mesh label, a cell
            %   array of names: code c names entry c + 1.
            t = gamut.internal.field(s.describe(name), 'category', '');
            if isempty(t)
                error('gamut:usage', '%s has no category table; its codes are its values', name);
            end
            v = gamut_mex('table', s.Handle, t);
        end

        function t = table(s)
            %TABLE The run table as a MATLAB table: parameters, labels, scalars.
            t = table();
            for n = reshape(s.names('parameters'), 1, [])
                t.(n{1}) = s.getParameter(n{1});
            end
            for n = reshape(s.names('labels'), 1, [])
                t.(n{1}) = categorical(s.getLabel(n{1}));
            end
            for n = reshape(s.names('scalars'), 1, [])
                t.(n{1}) = s.getScalar(n{1});
            end
        end

        function rows = select(s, where)
            %SELECT The (1-based) rows `where` selects.
            rows = double(gamut_mex('select', s.Handle, where)) + 1;
        end
    end

    methods (Hidden)
        function abandon(s, remove)
            %ABANDON Releases the file without finishing it; with remove
            %true, deletes a file this handle created.  For giving up after
            %an error.
            if ~isempty(s.Handle)
                h = s.Handle;
                s.Handle = [];
                gamut_mex('abandon', h, logical(remove));
            end
        end

        function v = info1(s, key)
            c = gamut_mex('info', s.Handle, key);
            if isempty(c), v = ''; else, v = c{1}; end
        end

        function code = resultCode(s, name)
            code = 6;
            if strcmp(gamut.internal.field(s.describe(name), 'dtype', ''), 'float32'), code = 5; end
        end

        function o = opts(~, args)
            p = inputParser;
            p.addParameter('rows', ':');    % ':' every row; [] none, as select may return
            p.addParameter('nodes', ':');
            p.addParameter('cells', ':');
            p.parse(args{:});
            o = p.Results;
        end

        function p = pos(~, x)
            % 1-based MATLAB positions to the core's 0-based ones: ':' is every
            % position and [] none.  Only whole-number positions; a logical
            % mask is find(mask).
            if ischar(x) || isstring(x)
                if ~strcmp(x, ':'), error('gamut:usage', 'positions are '':'' or numbers'); end
                p = ':';
            elseif isempty(x)
                p = zeros(0, 1);
            else
                if islogical(x) || ~isnumeric(x) || any(x(:) ~= fix(x(:)))
                    error('gamut:usage', 'positions are whole numbers (for a mask, use find)');
                end
                p = double(x(:)) - 1;
            end
        end

        function stageCells(s, cells, labels)
            % As given: the gateway reads each integer class exactly, and a
            % double conversion would round int64 codes above 2^53.
            if ~isempty(cells)
                gamut_mex('geometry_cells', s.Handle, cells{1}, cells{2}, cells{3});
            end
            if isstruct(labels)
                ln = fieldnames(labels);
                for k = 1:numel(ln)
                    gamut_mex('geometry_label', s.Handle, ln{k}, labels.(ln{k}));
                end
            end
        end

        function ids = commit(s, n, columns, fields, points, cells, meshLabels)
            h = s.Handle;
            gamut_mex('batch_begin', h, n);
            names = fieldnames(columns);
            groupNames = {};
            for k = 1:numel(names)
                v = columns.(names{k});
                if iscell(v) || isstring(v) || iscategorical(v)
                    v = cellstr(v);
                    gamut_mex('batch_names', h, names{k}, v);
                    if strcmp(names{k}, s.Group), groupNames = v; end
                elseif islogical(v)
                    words = {'false', 'true'};
                    gamut_mex('batch_names', h, names{k}, words(double(v) + 1));
                else
                    gamut_mex('batch_values', h, names{k}, v(:));
                end
            end
            fn = fieldnames(fields);
            for k = 1:numel(fn)
                gamut_mex('batch_values', h, fn{k}, fields.(fn{k}));
            end
            if ~isempty(points)
                if ~isempty(s.Group)
                    for i = 1:numel(groupNames)
                        if isempty(points{i}), continue; end
                        gamut_mex('geometry_begin', h);
                        gamut_mex('geometry_points', h, points{i});
                        s.stageCells(cellAt(cells, i), labelsAt(meshLabels, i));
                        gamut_mex('batch_geometry_for_member', h, groupNames{i});
                    end
                else
                    for i = 1:numel(points)
                        gamut_mex('geometry_begin', h);
                        gamut_mex('geometry_points', h, points{i});
                        s.stageCells(cellAt(cells, i), labelsAt(meshLabels, i));
                        gamut_mex('batch_geometry_for_row', h);
                    end
                end
            end
            first = gamut_mex('batch_commit', h);
            ids = first + (0:n - 1);
        end
    end
end

function c = cellAt(cells, i)
if isempty(cells), c = {}; else, c = cells{i}; end
end

function l = labelsAt(labels, i)
if isempty(labels) || ~iscell(labels), l = struct(); else, l = labels{i}; end
end
