%UNCERTAIN Uncertainty and gradients beside the values they describe.
%   Each run stores a lift coefficient with its standard deviation and two
%   quantiles, and its derivative with respect to angle of attack. Each
%   names the result it describes, so a reader finds them without naming
%   conventions. examples/06_uncertainty_gradients.py and the Julia and
%   C++ examples are the same program and print the same lines.

alpha = linspace(0, 8, 9)';
cl = 0.11 * alpha;
spread = 0.01 + 0.002 * alpha;
study = gamut.create('uncertain.gamut', 'writer', 'example ensemble', ...
    'parameters', struct('alpha', struct('units', 'degree', 'role', 'condition')), ...
    'scalars', struct('cl', '1', ...
        'cl_std', struct('units', '1', 'of', 'cl', 'statistic', 'std'), ...
        'cl_p05', struct('units', '1', 'of', 'cl', 'statistic', 'quantile', 'q', 0.05), ...
        'cl_p95', struct('units', '1', 'of', 'cl', 'statistic', 'quantile', 'q', 0.95), ...
        'dcl_dalpha', struct('units', 'degree-1', 'of', 'cl', 'withRespectTo', 'alpha')));
study.addRuns(struct('alpha', alpha, 'cl', cl, 'cl_std', spread, ...
    'cl_p05', cl - 1.645 * spread, 'cl_p95', cl + 1.645 * spread, 'dcl_dalpha', repmat(0.11, 9, 1)));
study.close();

study = gamut.open('uncertain.gamut');
related = study.related('cl');
fprintf('the std of cl: %s\n', related.std);
fprintf('its 0.05 and 0.95 quantiles: %s %s\n', related.quantiles(0.05), related.quantiles(0.95));
fprintf('its derivative with respect to alpha: %s\n', related.derivatives('alpha'));
low = study.getScalar(related.quantiles(0.05));
high = study.getScalar(related.quantiles(0.95));
fprintf('90 %% band at 8 degrees: %.3f to %.3f\n', low(end), high(end));
study.close();
