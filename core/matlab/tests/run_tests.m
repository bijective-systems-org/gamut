function run_tests()
% MATLAB tests of the mestra wrapper over the shared core.  Run with
%   matlab -batch "addpath('<abs>/core/matlab/tests'); run_tests"
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
p = fullfile(tmp, 'polar.mes');
s = mestra.create(p, 'writer', 'matlab tests', ...
    'parameters', struct('mach', struct('units', '1', 'role', 'condition'), 'alpha', 'degree'), ...
    'labels', struct('status', struct('role', 'status', 'categories', {{'converged', 'failed'}})), ...
    'scalars', struct('cl', '1', 'cd', '1'), 'constants', struct('s_ref', {{12.5, 'm2'}}));
for i = 1:5
    st = 'converged'; if i == 3, st = 'failed'; end
    s.addRun(struct('mach', 0.3 + 0.1 * (i - 1), 'alpha', i - 1, 'status', st, ...
        'cl', 0.1 * i, 'cd', single(0.01)));
end
s.close();
r = mestra.open(p);
ok(r.rowCount() == 5, 'row count');
ok(strcmp(r.type(), 'table'), 'type');
cl = r.getScalar('cl');
ok(isequal(size(cl), [5 1]) && abs(cl(2) - 0.2) < 1e-15, 'cl column');
ok(isa(r.getScalar('cd'), 'single'), 'cd kept single');
st = r.getLabel('status', 'rows', 3);
ok(strcmp(st{1}, 'failed'), 'label by 1-based row');
ok(isequal(r.select('mach > 0.45'), [3; 4; 5]), 'select 1-based');
ok(r.getConstant('s_ref') == 12.5, 'constant');
ids = r.getRowIds();
ok(isequal(ids', int64(0:4)), 'row ids 0-based values');
t = r.table();
ok(height(t) == 5 && any(strcmp(t.Properties.VariableNames, 'cl')), 'table');
r.close();
f = mestra.validate(p);
ok(numel(f) == 1 && strcmp(f(1).rule, 'W2'), 'validate: one W2');

% A shared mesh with fields; logical (row, node) order.
p = fullfile(tmp, 'sweep.mes');
[X, Y] = meshgrid(0:2, 0:1);
pts = [X(:) Y(:)];        % 6 nodes, MATLAB column order of the grid
s = mestra.create(p, 'writer', 'matlab tests', 'mesh', 'shared', 'per', 'fixed', ...
    'coordinates', struct('units', 'm', 'axes', 2), 'parameters', struct('k', '1'), ...
    'fields', struct('pf', struct('units', 'Pa', 'at', 'node')));
s.setMesh(pts, {uint8([9 9]), [0 4 8], [0 2 3 1 2 4 5 3]});
P = reshape(1:18, 3, 6);  % 3 runs x 6 nodes
s.addRuns(struct('k', [1; 2; 3]), 'fields', struct('pf', P));
s.close();
r = mestra.open(p);
ok(isequal(r.getField('pf'), P), 'field round trip, run x node');
ok(isequal(r.getField('pf', 'rows', 2, 'nodes', [2 3]), P(2, [2 3])), 'field selection 1-based');
ok(isequal(r.getPoints(), pts), 'points');
[types, offsets, conn] = r.getCells();
ok(isequal(types', uint8([9 9])) && offsets(end) == 8 && conn(1) == 0, 'cells');
r.close();
rt = mestra.open(p, 'threads', 4);
ok(isequal(rt.getField('pf'), P), 'parallel read');
rt.close();

% Append in place.
s = mestra.open(p, 'mode', 'a');
s.addRun(struct('k', 4), 'fields', struct('pf', 100:105));
s.close();
r = mestra.open(p);
ok(r.rowCount() == 4 && isequal(r.getField('pf', 'rows', 4), 100:105), 'append');
r.close();

% Model files: the built-in nearest model with one input (MATLAB cannot tell
% a one-element array from a number; the gateway keeps the ranks), and a
% registered plug-in serving values and std.
mp = fullfile(tmp, 'nearest.mes');
s = mestra.createModel(mp, 'writer', 'matlab tests', ...
    'parameters', struct('alpha', struct('units', 'degree', 'lower', 0, 'upper', 10)), ...
    'scalars', struct('cl', struct('units', '1', 'model', 'fit', 'output', 'cl')));
s.addModel('fit', mestra.Nearest({'alpha'}, 0, 10, [0; 5; 10], struct('cl', [0.1; 0.5; 1.0])), ...
    {'alpha'});
s.close();
ok(isempty(mestra.validate(mp)), 'nearest model file validates');

% A refused close keeps the file open to fix and close again.
rp = fullfile(tmp, 'refused.mes');
s = mestra.createModel(rp, 'writer', 'matlab tests', ...
    'parameters', struct('alpha', struct('units', 'degree', 'lower', 0, 'upper', 10)), ...
    'scalars', struct('cl', struct('units', '1', 'model', 'fit', 'output', 'cl')));
try
    s.close();
    ok(false, 'close without a model refused');
catch err
    ok(strcmp(err.identifier, 'mestra:E16'), ['refused close: ' err.identifier]);
end
s.addModel('fit', mestra.Nearest({'alpha'}, 0, 10, [0; 10], struct('cl', [1; 2])), {'alpha'});
s.close();
ok(isempty(mestra.validate(rp)), 'closed after the fix');
out = mestra.evaluate(mp, struct('alpha', [1; 4; 9]));
ok(isequal(out.getScalar('cl'), [0.1; 0.5; 1.0]), 'nearest evaluated');
ok(isequal(out.getParameter('alpha'), [1; 4; 9]), 'inputs kept');
tmpPath = out.Path;
out.close();
ok(~isfile(tmpPath), 'temporary evaluated file removed on close');
r = mestra.open(mp);
numbers = mestra_mex('model_numbers', r.Handle, 'fit');
r.close();
back = mestra.Nearest.load(numbers);
ok(isequal(back.X, [0; 5; 10]) && isequal(back.Lower, 0), 'nearest numbers read back');

lp = fullfile(tmp, 'linear.mes');
s = mestra.createModel(lp, 'writer', 'matlab tests', ...
    'parameters', struct('x', struct('units', 'm', 'lower', -1, 'upper', 1)), ...
    'scalars', struct('y', struct('units', '1', 'model', 'lin', 'output', 'y'), ...
        'y_std', struct('units', '1', 'model', 'lin', 'output', 'y', 'of', 'y', ...
                        'statistic', 'std')));
lin = testmodels.Linear(); lin.A = 1; lin.B = 2; lin.Std = 0.25; lin.Input = 'x'; lin.Output = 'y';
s.addModel('lin', lin, {'x'});
s.close();
try
    mestra.evaluate(lp, struct('x', [0; 0.5]));
    ok(false, 'unregistered type refused');
catch err
    ok(contains(err.message, 'not registered'), ['unregistered type: ' err.message]);
end
mestra.registerModelType('testmodels.Linear');
ep = fullfile(tmp, 'evaluated.mes');
out = mestra.evaluate(lp, struct('x', [0; 0.5]), 'path', ep);
ok(isequal(out.getScalar('y'), [1; 2]) && isequal(out.getScalar('y_std'), [0.25; 0.25]), ...
    'plug-in values and std');
out.close();
ok(isfile(ep) && isempty(mestra.validate(ep)), 'evaluated file kept and valid');

% Errors carry their rule.
try
    mestra.create(fullfile(tmp, 'bad.mes'), 'writer', 'w', 'parameters', struct('x', 'm//s'));
    ok(false, 'bad units refused');
catch err
    ok(strcmp(err.identifier, 'mestra:E7'), ['bad units identifier: ' err.identifier]);
end
% In a mesh file too, a declaration error is its own, and the half-made
% file is removed.
bad = fullfile(tmp, 'badmesh.mes');
try
    mestra.create(bad, 'writer', 'w', 'mesh', 'shared', 'per', 'fixed', ...
        'coordinates', struct('units', 'm', 'axes', 2), ...
        'fields', struct('q', struct('units', 'm//s', 'at', 'node')));
    ok(false, 'bad field units refused');
catch err
    ok(strcmp(err.identifier, 'mestra:E7'), ['mesh file bad units identifier: ' err.identifier]);
    ok(~isfile(bad), 'half-declared mesh file removed');
end
try
    r = mestra.open(p); r.close(); r.getField('pf');
    ok(false, 'closed file refused');
catch err
    ok(contains(err.message, 'closed') || strcmp(err.identifier, 'mestra:usage'), 'closed handle');
end

fprintf('%d checks, %d failures\n', checks, failures);
if failures > 0, error('mestra:tests', '%d failures', failures); end
end
