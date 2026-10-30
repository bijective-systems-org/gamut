function [points, cells, t, r] = cylinderRing(radius, nTheta, nR)
%CYLINDERRING The ring of quadrilaterals around a cylinder that several
%   examples share, as examples/_cylinder.py's ring: points (nodes x 2),
%   cells {types, offsets, connectivity} and each node's polar coordinates.
if nargin < 1, radius = 1; end
if nargin < 2, nTheta = 48; end
if nargin < 3, nR = 12; end
theta = linspace(0, 2 * pi, nTheta + 1); theta = theta(1:end - 1);
[t, r] = ndgrid(theta, radius * logspace(0, log10(6), nR));   % around each ring first
t = t(:); r = r(:);
points = [r .* cos(t), r .* sin(t)];
[i, j] = ndgrid(0:nTheta - 1, 0:nR - 2);
i = i(:); j = j(:);
quads = [j * nTheta + i, j * nTheta + mod(i + 1, nTheta), ...
         (j + 1) * nTheta + mod(i + 1, nTheta), (j + 1) * nTheta + i]';
cells = {repmat(uint8(9), 1, numel(i)), 0:4:4 * numel(i), quads(:)'};   % VTK quadrilaterals
end
