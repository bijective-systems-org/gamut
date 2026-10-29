function run_tests()
% MATLAB tests of the Gamut wrapper over the shared core.  Run with
%   matlab -batch "addpath('<abs>/matlab/tests'); run_tests"
here = fileparts(mfilename('fullpath'));
addpath(fileparts(here));
tmp = tempname; mkdir(tmp);
cleanup = onCleanup(@() rmdir(tmp, 's'));
failures = 0; checks = 0;

    function ok(cond, what)
        checks = checks + 1;
        if ~cond
            failures = failures + 1;
            fprintf(2, 'FAIL: %s\n', what);
        end
    end

% A table, one run at a time.
p = fullfile(tmp, 'polar.gamut');
s = gamut.create(p, 'writer', 'matlab tests', ...
    'parameters', struct('mach', struct('units', '1', 'role', 'condition'), 'alpha', 'degree'), ...
    'labels', struct('status', struct('role', 'status', 'categories', {{'converged', 'failed'}})), ...
    'scalars', struct('cl', '1', 'cd', '1'), 'constants', struct('s_ref', {{12.5, 'm2'}}));
for i = 1:5
    st = 'converged'; if i == 3, st = 'failed'; end
    s.addRun(struct('mach', 0.3 + 0.1 * (i - 1), 'alpha', i - 1, 'status', st, ...
        'cl', 0.1 * i, 'cd', single(0.01)));
end
s.close();
r = gamut.open(p);
ok(r.rowCount() == 5, 'row count');
ok(strcmp(r.type(), 'table'), 'type');
cl = r.getScalar('cl');
ok(isequal(size(cl), [5 1]) && abs(cl(2) - 0.2) < 1e-15, 'cl column');
ok(isa(r.getScalar('cd'), 'single'), 'cd kept single');
st = r.getLabel('status', 'rows', 3);
ok(strcmp(st{1}, 'failed'), 'label by 1-based row');
ok(isequal(r.select('mach > 0.45'), [3; 4; 5]), 'select 1-based');
ok(isequal(r.select('mach>0.45'), [3; 4; 5]), 'select without spaces');
c = r.categories('status');
ok(isequal(c(:)', {'converged', 'failed'}), 'category table');
ok(r.getConstant('s_ref') == 12.5, 'constant');
ids = r.getRowIds();
ok(isequal(ids', int64(0:4)), 'row ids 0-based values');
t = r.table();
ok(height(t) == 5 && any(strcmp(t.Properties.VariableNames, 'cl')), 'table');
r.close();
f = gamut.validate(p);
ok(numel(f) == 1 && strcmp(f(1).rule, 'W2'), 'validate: one W2');

% A shared mesh with fields; logical (row, node) order.
p = fullfile(tmp, 'sweep.gamut');
[X, Y] = meshgrid(0:2, 0:1);
pts = [X(:) Y(:)];        % 6 nodes, MATLAB column order of the grid
s = gamut.create(p, 'writer', 'matlab tests', 'mesh', 'shared', 'per', 'fixed', ...
    'coordinates', struct('units', 'm', 'axes', 2), 'parameters', struct('k', '1'), ...
    'fields', struct('pf', struct('units', 'Pa', 'at', 'node')));
s.setMesh(pts, {uint8([9 9]), [0 4 8], [0 2 3 1 2 4 5 3]});
P = reshape(1:18, 3, 6);  % 3 runs x 6 nodes
s.addRuns(struct('k', [1; 2; 3]), 'fields', struct('pf', P));
s.close();
r = gamut.open(p);
ok(isequal(r.getField('pf'), P), 'field round trip, run x node');
ok(isequal(r.getField('pf', 'rows', 2, 'nodes', [2 3]), P(2, [2 3])), 'field selection 1-based');
ok(isequal(r.getPoints(), pts), 'points');
[types, offsets, conn] = r.getCells();
ok(isequal(types', uint8([9 9])) && offsets(end) == 8 && conn(1) == 0, 'cells');
r.close();
rt = gamut.open(p, 'threads', 4);
ok(isequal(rt.getField('pf'), P), 'parallel read');
rt.close();

% Append in place.
s = gamut.open(p, 'mode', 'a');
s.addRun(struct('k', 4), 'fields', struct('pf', 100:105));
s.close();
r = gamut.open(p);
ok(r.rowCount() == 4 && isequal(r.getField('pf', 'rows', 4), 100:105), 'append');
r.close();

% How far each row lies outside its parameter's bounds, rows from 1, and
% the core's refusals: no bounds, not a parameter, a row that does not exist.
p = fullfile(tmp, 'bounds.gamut');
s = gamut.create(p, 'writer', 'matlab tests', ...
    'parameters', struct('x', struct('units', 'm', 'lower', 0, 'upper', 1), 'mach', '1'), ...
    'scalars', struct('cl', '1'));
s.addRuns(struct('x', [-0.5; 0; 0.25; 1; 1.5], 'mach', 0.5 * ones(5, 1), 'cl', zeros(5, 1)));
s.close();
r = gamut.open(p);
ok(isequal(r.outside('x'), [-0.5; 0; 0; 0; 0.5]), 'outside: below, on a bound, inside, above');
ok(isequal(r.outside('x', 'rows', [1 5]), [-0.5; 0.5]), 'outside: rows from 1');
for refusal = {{'mach', [], 'mach declares no bounds'}, {'cl', [], 'no parameter'}, ...
               {'x', 6, 'outside the 5 positions'}}
    [name, rows, says] = refusal{1}{:};
    try
        r.outside(name, 'rows', rows);
        ok(false, ['outside refused: ' says]);
    catch err
        ok(contains(err.message, says), ['outside refused: ' err.message]);
    end
end
r.close();

% Model files: the built-in nearest model with one input (MATLAB cannot tell
% a one-element array from a number; the gateway keeps the ranks), and a
% registered plug-in serving values and std.
mp = fullfile(tmp, 'nearest.gamut');
s = gamut.createModel(mp, 'writer', 'matlab tests', 'portionMarking', 'Example marking', ...
    'parameters', struct('alpha', struct('units', 'degree', 'lower', 0, 'upper', 10)), ...
    'scalars', struct('cl', struct('units', '1', 'model', 'fit', 'output', 'cl')));
s.addModel('fit', gamut.Nearest({'alpha'}, 0, 10, [0; 5; 10], struct('cl', [0.1; 0.5; 1.0])), ...
    {'alpha'});
s.close();
ok(isempty(gamut.validate(mp)), 'nearest model file validates');
r = gamut.open(mp);
ok(strcmp(r.describe().portion_marking, 'Example marking'), 'portion marking read as written');
r.close();

% A refused close keeps the file open to fix and close again.
rp = fullfile(tmp, 'refused.gamut');
s = gamut.createModel(rp, 'writer', 'matlab tests', ...
    'parameters', struct('alpha', struct('units', 'degree', 'lower', 0, 'upper', 10)), ...
    'scalars', struct('cl', struct('units', '1', 'model', 'fit', 'output', 'cl')));
try
    s.close();
    ok(false, 'close without a model refused');
catch err
    ok(strcmp(err.identifier, 'gamut:E16'), ['refused close: ' err.identifier]);
end
s.addModel('fit', gamut.Nearest({'alpha'}, 0, 10, [0; 10], struct('cl', [1; 2])), {'alpha'});
s.close();
ok(isempty(gamut.validate(rp)), 'closed after the fix');
out = gamut.evaluate(mp, struct('alpha', [1; 4; 9]));
ok(isequal(out.getScalar('cl'), [0.1; 0.5; 1.0]), 'nearest evaluated');
ok(isequal(out.getParameter('alpha'), [1; 4; 9]), 'inputs kept');
ok(strcmp(out.describe().portion_marking, 'Example marking'), 'portion marking copied into the answer');
tmpPath = out.Path;
out.close();
ok(~isfile(tmpPath), 'temporary evaluated file removed on close');
lastwarn('');
out = gamut.evaluate(mp, struct('alpha', [-2; 5; 12]));
[~, id] = lastwarn();
ok(strcmp(id, 'gamut:W4'), 'an input outside the domain warns');
ok(isequal(out.outside('alpha'), [-2; 0; 2]), 'the answer marks each input outside the domain');
out.close();
r = gamut.open(mp);
numbers = r.modelNumbers('fit');
r.close();
back = gamut.Nearest.load(numbers);
ok(isequal(back.X, [0; 5; 10]) && isequal(back.Lower, 0), 'nearest numbers read back');

lp = fullfile(tmp, 'linear.gamut');
s = gamut.createModel(lp, 'writer', 'matlab tests', ...
    'parameters', struct('x', struct('units', 'm', 'lower', -1, 'upper', 1)), ...
    'scalars', struct('y', struct('units', '1', 'model', 'lin', 'output', 'y'), ...
        'y_std', struct('units', '1', 'model', 'lin', 'output', 'y', 'of', 'y', ...
                        'statistic', 'std'), ...
        'y_p90', struct('units', '1', 'model', 'lin', 'output', 'y', 'of', 'y', ...
                        'statistic', 'quantile', 'q', 0.9), ...
        'dy_dx', struct('units', 'm-1', 'model', 'lin', 'output', 'y', 'of', 'y', ...
                        'withRespectTo', 'x')));
lin = testmodels.Linear(); lin.A = 1; lin.B = 2; lin.Std = 0.25; lin.Input = 'x'; lin.Output = 'y';
s.addModel('lin', lin, {'x'});
s.close();
try
    gamut.evaluate(lp, struct('x', [0; 0.5]));
    ok(false, 'unregistered type refused');
catch err
    ok(contains(err.message, 'not registered'), ['unregistered type: ' err.message]);
end
gamut.registerModelType('testmodels.Linear');
ep = fullfile(tmp, 'evaluated.gamut');
out = gamut.evaluate(lp, struct('x', [0; 0.5]), 'path', ep);
ok(isequal(out.getScalar('y'), [1; 2]) && isequal(out.getScalar('y_std'), [0.25; 0.25]), ...
    'plug-in values and std');
ok(max(abs(out.getScalar('y_p90') - [1.2; 2.2])) < 1e-12, 'plug-in quantile, from a containers.Map');
ok(isequal(out.getScalar('dy_dx'), [2; 2]), 'plug-in derivative');
out.close();
ok(isfile(ep) && isempty(gamut.validate(ep)), 'evaluated file kept and valid');

% Copies between files: append, extract, writeCopy.
ca = fullfile(tmp, 'ca.gamut'); cb = fullfile(tmp, 'cb.gamut'); ce = fullfile(tmp, 'ce.gamut');
cw = fullfile(tmp, 'cw.gamut');
s = gamut.create(ca, 'writer', 'w', 'parameters', struct('x', 'm'), ...
    'labels', struct('case', 'categorical'));
s.addRuns(struct('x', [1; 2], 'case', {{'p'; 'q'}}));
s.close();
s = gamut.create(cb, 'writer', 'w', 'parameters', struct('x', 'm'), ...
    'labels', struct('case', 'categorical'));
s.addRuns(struct('x', [3; 4], 'case', {{'r'; 'p'}}));
s.close();
ok(gamut.append(ca, cb) == 2, 'append returns the rows added');
gamut.extract(ca, ce, [2 4]);
r = gamut.open(ce);
ok(isequal(r.getRowIds(), [1; 3]) && isequal(r.getLabel('case'), {'q'; 'p'}), 'extract keeps ids');
r.close();
gamut.writeCopy(ca, cw);
r = gamut.open(cw); q = gamut.open(ca);
ok(strcmp(r.describe().file_id, q.describe().file_id) && isequal(r.getParameter('x'), [1; 2; 3; 4]), ...
    'writeCopy keeps identity and values');
ok(~isfield(r.describe(), 'portion_marking'), 'no marking unless set');
r.close(); q.close();
mm = fullfile(tmp, 'marked.gamut'); me = fullfile(tmp, 'marked_part.gamut'); mw = fullfile(tmp, 'marked_copy.gamut');
s = gamut.create(mm, 'writer', 't', 'parameters', struct('x', 'm'), 'portionMarking', 'Example marking');
s.addRuns(struct('x', [1; 2]));
s.close();
gamut.extract(mm, me, 2);
gamut.writeCopy(mm, mw);
for p = {mm, me, mw}
    r = gamut.open(p{1});
    ok(strcmp(r.describe().portion_marking, 'Example marking'), ['portion marking kept in ' p{1}]);
    r.close();
end
try
    gamut.append(ca, ca);
    ok(false, 'append to itself refused');
catch err
    ok(startsWith(err.identifier, 'gamut:'), 'append to itself refused');
end

% Errors carry their rule.
try
    gamut.create(fullfile(tmp, 'bad.gamut'), 'writer', 'w', 'parameters', struct('x', 'm//s'));
    ok(false, 'bad units refused');
catch err
    ok(strcmp(err.identifier, 'gamut:E7'), ['bad units identifier: ' err.identifier]);
end
% In a mesh file too, a declaration error is its own, and the half-made
% file is removed.
bad = fullfile(tmp, 'badmesh.gamut');
try
    gamut.create(bad, 'writer', 'w', 'mesh', 'shared', 'per', 'fixed', ...
        'coordinates', struct('units', 'm', 'axes', 2), ...
        'fields', struct('q', struct('units', 'm//s', 'at', 'node')));
    ok(false, 'bad field units refused');
catch err
    ok(strcmp(err.identifier, 'gamut:E7'), ['mesh file bad units identifier: ' err.identifier]);
    ok(~isfile(bad), 'half-declared mesh file removed');
end
try
    r = gamut.open(p); r.close(); r.getField('pf');
    ok(false, 'closed file refused');
catch err
    ok(contains(err.message, 'closed') || strcmp(err.identifier, 'gamut:usage'), 'closed handle');
end

% A table, as readtable gives one, adds its rows as runs, and a study's own
% table (labels as categorical) adds them again.
p = fullfile(tmp, 'from_table.gamut');
runs = table([0; 2; 4], {'converged'; 'converged'; 'failed'}, [0; 0.22; NaN], ...
    'VariableNames', {'alpha', 'status', 'cl'});
w = gamut.create(p, 'writer', 'tests', 'parameters', struct('alpha', 'degree'), ...
    'labels', struct('status', struct('role', 'status', 'categories', {{'converged', 'failed'}})), ...
    'scalars', struct('cl', '1'));
ids = w.addRuns(runs);
ok(isequal(ids(:), [0; 1; 2]), 'a table adds its rows');
w.close();
r = gamut.open(p);
back = r.table();
r.close();
w = gamut.open(p, 'mode', 'a');
w.addRuns(back);
w.close();
r = gamut.open(p);
ok(r.rowCount() == 6 && isequal(cellstr(r.getLabel('status')), ...
    {'converged'; 'converged'; 'failed'; 'converged'; 'converged'; 'failed'}), 'a study''s table adds again');
r.close();

% Cell offsets of the wrong length are refused before the core reads them,
% and a mesh without per is the core's refusal, as in every language.
p = fullfile(tmp, 'short_offsets.gamut');
w = gamut.create(p, 'writer', 'tests', 'mesh', 'shared', 'per', 'fixed', ...
    'coordinates', struct('units', 'm', 'axes', 2), 'parameters', struct('k', '1'));
try
    w.setMesh([0 0; 1 0; 0 1], {5, 0, [0 1 2]});
    ok(false, 'short offsets refused');
catch err
    ok(strcmp(err.identifier, 'gamut:E5'), 'short offsets refused');
end
w.abandon(true);
try
    gamut.create(fullfile(tmp, 'no_per.gamut'), 'writer', 'tests', 'mesh', 'shared');
    ok(false, 'a mesh without per refused');
catch err
    ok(strcmp(err.identifier, 'gamut:E6'), 'a mesh without per refused');
end

for bound = {struct('units', '1', 'lower', 0), struct('units', '1', 'upper', 1)}
    try
        gamut.create(fullfile(tmp, 'one_bound.gamut'), 'writer', 'tests', ...
            'parameters', struct('x', bound{1}));
        ok(false, 'one bound refused');
    catch err
        ok(strcmp(err.identifier, 'gamut:E16'), 'one bound refused');
    end
end

% The examples in examples/matlab run: one_mesh writes a valid file, and
% the README's sweep, and the same file read with ncread, print its line.
examples = fullfile(fileparts(fileparts(here)), 'examples', 'matlab');
if isfile(fullfile(examples, 'one_mesh.m'))
    exampleDir = fullfile(tmp, 'examples'); mkdir(exampleDir);
    run_example(fullfile(examples, 'one_mesh.m'), exampleDir);
    ok(isempty(gamut.validate(fullfile(exampleDir, 'cylinder.gamut'))), ...
        'the MATLAB example writes a valid file');
    readme = fileread(fullfile(fileparts(fileparts(here)), 'README.md'));
    line = regexp(readme, 'lift of the runs that converged:[^\r\n]*', 'match', 'once');
    prints = @(out) ~isempty(line) && any(strcmp(splitlines(string(out)), line));
    ok(prints(run_example(fullfile(examples, 'sweep.m'), exampleDir)), ...
        'the MATLAB sweep prints the README''s line');
    ok(prints(run_example(fullfile(examples, 'read_with_ncread.m'), exampleDir)), ...
        'ncread reads the sweep alike');

    % The model examples/07_models.py fitted in Python, evaluated here with
    % the MATLAB class of its type: the folder MODEL_FILES names holds the
    % files that script wrote (CI writes them before this suite runs).
    models = getenv('MODEL_FILES');
    if isempty(models)
        fprintf(['the model example was not run: set MODEL_FILES to a folder where ' ...
            'examples/07_models.py ran\n']);
    else
        copyfile(fullfile(models, 'lift_model.gamut'), exampleDir);
        copyfile(fullfile(examples, 'Polynomial.m'), exampleDir);
        line = regexp(readme, 'the model''s lift at[^\r\n]*', 'match', 'once');
        printed = splitlines(string(run_example(fullfile(examples, 'evaluate_model.m'), exampleDir)));
        ok(~isempty(line) && any(strcmp(printed, line)), ...
            'MATLAB evaluates the model fitted in Python and prints the README''s line');
        page = fileread(fullfile(fileparts(fileparts(here)), 'docs', 'guide', '12-matlab.md'));
        marks = regexp(page, 'degrees outside the fitted range:[^\r\n]*', 'match', 'once');
        ok(~isempty(marks) && any(strcmp(printed, marks)), ...
            'the answer marks the angle outside the fitted range as the MATLAB page shows');
        % The same class saves a model fitted in MATLAB: its coefficients
        % are stored as a vector, as numpy.polyfit's are.
        back = cd(exampleDir);
        mp = fullfile(exampleDir, 'lift_matlab.gamut');
        alpha = (0:2:10)';
        s = gamut.createModel(mp, 'writer', 'matlab tests', ...
            'parameters', struct('alpha', struct('units', 'degree', 'lower', 0, 'upper', 10)), ...
            'scalars', struct('cl', struct('units', '1', 'model', 'fit', 'output', 'cl')));
        s.addModel('fit', Polynomial(polyfit(alpha, 0.11 * alpha, 2)), {'alpha'});
        s.close();
        r = gamut.open(mp);
        numbers = r.modelNumbers('fit');
        r.close();
        ok(isequal(size(numbers.coefficients), [3 1]), 'MATLAB-fitted coefficients stored as a vector');
        out = gamut.evaluate(mp, struct('alpha', [2.2; 7.9]));
        ok(max(abs(out.getScalar('cl') - [0.242; 0.869])) < 1e-12, 'MATLAB-fitted model evaluates');
        out.close();
        cd(back);
    end
end

% A field given nodes x runs, a refused threads value, compression off,
% and one member given two geometries in a batch.
p = fullfile(tmp, 'refusals.gamut');
cells = {uint8([9 9]), [0 4 8], [0 2 3 1 2 4 5 3]};
s = gamut.create(p, 'writer', 'matlab tests', 'mesh', 'shared', 'per', 'fixed', ...
    'coordinates', struct('units', 'm', 'axes', 2), 'parameters', struct('k', '1'), ...
    'fields', struct('pf', struct('units', 'Pa', 'at', 'node')), 'compression', false);
s.setMesh(pts, cells);
try
    s.addRuns(struct('k', [1; 2; 3]), 'fields', struct('pf', P'));
    ok(false, 'a field given nodes x runs refused');
catch err
    ok(contains(err.message, 'first axis has 6 entries but the batch has 3 runs'), ...
        ['transposed field: ' err.message]);
end
s.addRuns(struct('k', [1; 2; 3]), 'fields', struct('pf', P));
s.close();
r = gamut.open(p);
ok(isequal(r.getField('pf'), P), 'a file written with compression off reads back');
r.close();
try
    gamut.open(p, 'threads', 0);
    ok(false, 'threads 0 refused');
catch err
    ok(contains(err.message, 'threads'), ['threads 0: ' err.message]);
end
s = gamut.open(p, 'mode', 'a');      % the refused open left no handle behind
s.addRuns(struct('k', 4), 'fields', struct('pf', P(1, :)));
s.close();
fp = fullfile(tmp, 'members.gamut');
s = gamut.create(fp, 'writer', 'matlab tests', 'mesh', 'shared', 'per', 'group:member', ...
    'coordinates', struct('units', 'm', 'axes', 2), 'parameters', struct('k', '1'), ...
    'labels', struct('member', 'group'));
s.setMesh([], cells, struct(), 6);
try
    s.addRuns(struct('k', [1; 2], 'member', {{'a'; 'a'}}), 'points', {pts, 2 * pts});
    ok(false, 'one member given two geometries refused');
catch err
    ok(contains(err.message, 'two different geometries'), ['two geometries: ' err.message]);
end
s.addRuns(struct('k', [1; 2], 'member', {{'a'; 'a'}}), 'points', {pts, pts});
s.close();
cp = fullfile(tmp, 'changing.gamut');
s = gamut.create(cp, 'writer', 'matlab tests', 'mesh', 'changing', 'per', 'run', ...
    'coordinates', struct('units', 'm', 'axes', 2), 'parameters', struct('k', '1'), ...
    'fields', struct('q', struct('units', '1', 'at', 'node')));
s.addRun(struct('k', 1), 'fields', struct('q', (1:6)'), 'points', pts, 'cells', cells);
s.close();
r = gamut.open(cp);
q = r.getField('q', 'rows', 1);
ok(isequal(q(:), (1:6)'), 'a changing mesh takes a field as a column');
r.close();

% Strings as text, integer classes for cells, and a gateway kept loaded while a
% study is open.
sp = fullfile(tmp, 'strings.gamut');
s = gamut.create(string(sp), 'writer', "matlab tests", 'mesh', "shared", 'per', "fixed", ...
    'coordinates', struct('units', "m", 'axes', 2), 'parameters', struct('k', "1"), ...
    'fields', struct('pf', struct('units', "Pa", 'at', "node")));
s.setMesh(pts, {uint8([9 9]), int32([0 4 8]), int32([0 2 3 1 2 4 5 3])});
s.addRuns(struct('k', [1; 2; 3]), 'fields', struct("pf", P));
s.close();
r = gamut.open(string(sp));
ok(isequal(r.getField("pf"), P), 'a string path and name read like char ones');
[types, offsets] = r.getCells();
ok(isequal(double(offsets(:))', [0 4 8]), 'int32 offsets reach the file');
clear mex
ok(isequal(r.getField("pf", 'rows', 1), P(1, :)), 'an open study survives clear mex');
r.close();
% The gateway itself reads integers by class (the M layer converts first).
dp = fullfile(tmp, 'direct.gamut');
d = gamut.create(dp, 'writer', 'matlab tests', 'mesh', 'shared', 'per', 'fixed', ...
    'coordinates', struct('units', 'm', 'axes', 2), 'parameters', struct('k', '1'));
for bad = {{uint64(2)^63, 'out of range'}, {[0 4.5 8], 'whole numbers'}, {sparse([0 4 8]), 'sparse'}}
    gamut_mex('geometry_begin', d.Handle);
    gamut_mex('geometry_points', d.Handle, pts);
    try
        gamut_mex('geometry_cells', d.Handle, uint8([9 9]), bad{1}{1}, int64([0 2 3 1 2 4 5 3]));
        ok(false, ['refused offsets: ' bad{1}{2}]);
    catch err
        ok(contains(err.message, bad{1}{2}), ['refused offsets: ' err.message]);
    end
end
gamut_mex('geometry_begin', d.Handle);
gamut_mex('geometry_points', d.Handle, pts);
gamut_mex('geometry_cells', d.Handle, uint8([9 9]), single([0 4 8]), int16([0 2 3 1 2 4 5 3]));
gamut_mex('set_mesh', d.Handle);
d.addRun(struct('k', 1));
d.setNote('author', "Alice");
try
    gamut_mex('set_note', d.Handle, 'n', int64([]));
    ok(false, 'an empty int64 note refused');
catch err
    ok(contains(err.message, 'one number'), ['empty int64 note: ' err.message]);
end
d.close();
r = gamut.open(dp);
[~, offsets, conn] = r.getCells();
ok(isequal(double(offsets(:))', [0 4 8]) && isequal(double(conn(:))', [0 2 3 1 2 4 5 3]), ...
    'single offsets and int16 connectivity are read by their class');
r.close();

% [] selects nothing and ':' everything, so a select that matched nothing
% reads nothing; integer arguments reach the gateway in their own class.
r = gamut.open(p);
none = r.select('k > 99');
ok(isempty(none), 'a select matching nothing is empty');
ok(isempty(r.getParameter('k', 'rows', none)), 'reading the rows of an empty select reads none');
ok(numel(r.getParameter('k', 'rows', ':')) == numel(r.getParameter('k')) && numel(r.getParameter('k')) == 4, ...
    "':' and no rows read every row");
r.close();
wp = fullfile(tmp, 'wide_codes.gamut');
w = gamut.create(wp, 'writer', 'matlab tests', 'mesh', 'changing', 'per', 'run', ...
    'coordinates', struct('units', 'm', 'axes', 2), 'parameters', struct('k', '1'), ...
    'meshLabels', struct('zone', struct('at', 'cell')));
w.addRun(struct('k', 1), 'points', pts, 'cells', {int64(cells{1}), int64(cells{2}), int64(cells{3})}, ...
    'meshLabels', struct('zone', int64([2147483647; 1])));
w.close();
r = gamut.open(wp);
z = r.getMeshLabel('zone', 1);
ok(isequal(double(z(:))', [2147483647 1]), 'int64 cells and mesh-label codes pass through unconverted');
r.close();
% ':' as char or string is every position; nodes and cells are taken as
% given; extract takes ':' or nothing for every row.
r = gamut.open(p);
ok(isequal(size(r.getField('pf', 'rows', 1, 'nodes', ":")), [1 6]), 'nodes ":" is every node');
ok(isempty(r.getField('pf', 'rows', 1, 'cells', [])), 'cells [] is no cells');
r.close();
r = gamut.open(fullfile(tmp, 'sweep.gamut'));
ok(isequal(r.getPoints(":"), r.getPoints()), 'getPoints(":") is the fixed points');
ok(isequal(size(r.getPoints([])), [0 2]), 'getPoints([]) is no points, with the file''s two axes');
r.close();
try
    r = gamut.open(p);
    r.getField('pf', 'rows', 1, 'nodes', ":", 'cells', []);
    ok(false, 'nodes and cells together refused');
catch err
    ok(contains(err.message, 'not both'), ['nodes and cells: ' err.message]);
end
r.close();
xp = fullfile(tmp, 'extracted.gamut');
gamut.extract(p, xp);
r = gamut.open(xp); ok(r.rowCount() == 4, 'extract without rows takes every row'); r.close();
xa = fullfile(tmp, 'extracted_all.gamut');
gamut.extract(p, xa, ":");
r = gamut.open(xa); ok(r.rowCount() == 4, 'extract with ":" takes every row'); r.close();
xn = fullfile(tmp, 'extracted_none.gamut');
gamut.extract(p, xn, []);
r = gamut.open(xn); ok(r.rowCount() == 0, 'extract with [] takes no rows'); r.close();
% An int64 model input takes whole numbers in its range, here as singles,
% and refuses fractions, infinities, values past int64, logicals, complex
% and sparse inputs: int64() would round or saturate them silently.
ip = fullfile(tmp, 'int64_model.gamut');
s = gamut.createModel(ip, 'writer', 'matlab tests', ...
    'parameters', struct('n', struct('units', '1', 'dtype', 'int64', 'lower', 0, 'upper', 10)), ...
    'scalars', struct('y', struct('units', '1', 'model', 'fit', 'output', 'y')));
s.addModel('fit', gamut.Nearest({'n'}, 0, 10, [1; 9], struct('y', [1; 2])), {'n'});
s.close();
out = gamut.evaluate(ip, struct('n', single([2; 8])));
ok(isequal(out.getScalar('y'), [1; 2]), 'whole singles evaluate an int64 input');
out.close();
for bad = {2.5, Inf, 2^63, uint64(2)^63, true, 3 + 2i, sparse(3)}
    try
        o = gamut.evaluate(ip, struct('n', bad{1}));
        o.close();
        ok(false, sprintf('int64 input %s (%s) refused', num2str(full(bad{1})), class(bad{1})));
    catch err
        ok(strcmp(err.identifier, 'gamut:E4'), ['int64 input: ' err.message]);
    end
end
fprintf('%d checks, %d failures\n', checks, failures);
if failures > 0, error('gamut:tests', '%d failures', failures); end
end

function out = run_example(example, folder)
% Runs an example script in its own workspace and folder; returns what it
% printed.
old = cd(folder);
restore = onCleanup(@() cd(old));
copyfile(example, folder);
[~, name] = fileparts(example);
out = evalc(name);
end
