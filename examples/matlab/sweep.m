%SWEEP A sweep of a wing's angle of attack: six runs written, a seventh
%   added, then read. examples/00_readme.py and the Julia and C++ examples
%   are the same program and print the same line. Positions count from 1.

solve = @(alpha) 0.11 * alpha;          % stands for the solver: lift at one angle

study = gamut.create('sweep.gamut', 'writer', 'example sweep', ...
    'parameters', struct('alpha', struct('units', 'degree', 'role', 'condition')), ...
    'labels', struct('status', struct('role', 'status', 'categories', {{'converged', 'failed'}})), ...
    'scalars', struct('cl', '1'));
for alpha = 0:2:10
    study.addRun(struct('alpha', alpha, 'status', 'converged', 'cl', solve(alpha)));
end
study.close();

study = gamut.open('sweep.gamut', 'mode', 'a');
study.addRun(struct('alpha', 12, 'status', 'failed'));
study.close();

study = gamut.open('sweep.gamut');
cl = study.getScalar('cl', 'rows', study.select('status == converged'));
study.close();
fprintf('lift of the runs that converged: %s\n', strjoin(compose('%.2f', cl), ' '));
