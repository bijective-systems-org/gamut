function n = append(dst, src, varargin)
%APPEND Adds the rows of src to dst in place and returns how many.
%   n = gamut.append(dst, src)
%   n = gamut.append(dst, src, 'Marking', m)
%   The rows get new ids continuing dst's; category tables merge by name.
%   Both files need the same declarations (bounds may differ), the same
%   mesh, and one geometry for a group member found in both.  Everything
%   is checked before the first row is written.  A marked src whose
%   portion marking is not dst's is refused (gamut:E27); 'Marking' states
%   the marking the result carries, which dst then carries, whatever the
%   two files did.
%
%   Opening a marked file issues the warning gamut:marking, once per file;
%   warning('off', 'gamut:marking') turns it off.
p = inputParser;
p.addParameter('Marking', []);
p.parse(varargin{:});
if isnumeric(p.Results.Marking) && isempty(p.Results.Marking)   % not given; '' is refused
    n = gamut_mex('append', char(dst), char(src));
else
    n = gamut_mex('append', char(dst), char(src), char(p.Results.Marking));
end
end
