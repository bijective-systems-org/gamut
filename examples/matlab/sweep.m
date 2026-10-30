%SWEEP A sweep of a wing's angle of attack: six runs written, a seventh
%   added, then read. The six are written at once, as columns.
%   examples/00_readme.py and the Julia and C++ examples are the same
%   program and print the same line. Positions count from 1.

alpha = (0:2:10)';   % six angles of attack, in degrees
cl = 0.11 * alpha;   % stands for the solver's lift coefficients

study = gamut.create('sweep.gamut', 'writer', 'example sweep', ...
    'parameters', struct('alpha', struct('units', 'degree', ...
                                         'role', 'condition')), ...
    'labels', struct('status', struct('role', 'status', ...
                                      'categories', {{'converged', 'failed'}})), ...
    'scalars', struct('cl', '1'));
status = repmat({'converged'}, numel(alpha), 1);
study.addRuns(struct('alpha', alpha, 'cl', cl, 'status', {status}));
study.close();

study = gamut.open('sweep.gamut', 'mode', 'a');
study.addRun(struct('alpha', 12, 'status', 'failed'));
study.close();

study = gamut.open('sweep.gamut');
lift = study.getScalar('cl', 'rows', study.select('status == converged'));
study.close();
fprintf('lift of the runs that converged: %s\n', strjoin(compose('%.2f', lift), ' '));
