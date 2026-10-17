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

% Errors carry their rule.
try
    mestra.create(fullfile(tmp, 'bad.mes'), 'writer', 'w', 'parameters', struct('x', 'm//s'));
    ok(false, 'bad units refused');
catch err
    ok(strcmp(err.identifier, 'mestra:E7'), ['bad units identifier: ' err.identifier]);
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
