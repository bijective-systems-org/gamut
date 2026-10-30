%RUN_TABLE A study with no mesh: a table of runs, each with its inputs and
%   results. A sweep of a wing over Mach number and angle of attack.
%   examples/01_run_table.py and the Julia and C++ examples are the same
%   program and print the same lines. Positions count from 1.

study = gamut.create('polar.gamut', 'writer', 'example sweep', ...
    'parameters', struct('mach', struct('units', '1', 'role', 'condition'), ...
                         'alpha', struct('units', 'degree', 'role', 'condition')), ...
    'labels', struct('status', struct('role', 'status', 'categories', {{'converged', 'failed'}})), ...
    'scalars', struct('cl', '1', 'cd', '1'), ...
    'constants', struct('reference_area', {{12.5, 'm2'}}), ...
    'title', 'Wing A polar');
for mach = [0.6 0.7 0.8]
    for alpha = -2:2:8
        cl = 0.11 * alpha / sqrt(1 - mach^2);           % stand-in for a solver
        cd = 0.008 + 0.04 * cl^2;
        if mach == 0.8 && alpha == 8
            study.addRun(struct('mach', mach, 'alpha', alpha, 'status', 'failed', 'cl', NaN, 'cd', NaN));
        else
            study.addRun(struct('mach', mach, 'alpha', alpha, 'status', 'converged', 'cl', cl, 'cd', cd));
        end
    end
end
study.close();

study = gamut.open('polar.gamut');
fprintf('%d runs; %s\n', study.rowCount(), study.describe().title);
cl = study.getScalar('cl', 'rows', study.select('mach == 0.7'));
fprintf('lift at Mach 0.7: %s\n', strjoin(compose('%.3f', cl), ' '));
failed = study.select('status == failed');
mach = study.getParameter('mach', 'rows', failed);
alpha = study.getParameter('alpha', 'rows', failed);
fprintf('failed: Mach %.1f, alpha %g degree\n', mach, alpha);
fprintf('reference area: %g %s\n', study.getConstant('reference_area'), study.describe('reference_area').units);
study.close();
