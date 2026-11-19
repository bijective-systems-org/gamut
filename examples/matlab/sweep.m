%SWEEP Write three runs to first.gamut and read back the lift coefficients.

% Values at the same position belong to the same run.
alpha = [0; 2; 4];
cl = [0; 0.22; 0.44];

study = gamut.create('first.gamut', 'writer', 'example sweep', ...
    'parameters', struct('alpha', struct('units', 'degree', 'role', 'condition')), ...
    'scalars', struct('cl', '1'));
study.addRuns(struct('alpha', alpha, 'cl', cl));
study.close();

study = gamut.open('first.gamut');
lift = study.getScalar('cl');
study.close();

fprintf('cl: %s\n', strjoin(compose('%.2f', lift), ' '));
