function n = append(dst, src, varargin)
%APPEND Adds the rows of src to dst and returns how many.
%   n = gamut.append(dst, src)
%   n = gamut.append(dst, src, 'Marking', m)
%   n = gamut.append(dst, {src1, src2, ...})
%   The rows get new ids continuing dst's; category tables merge by name.
%   Both files need the same declarations (bounds may differ), the same
%   mesh, and one geometry for a group member found in both.  Everything
%   is checked before the first row is written.  A marked src whose
%   portion marking is not dst's is refused (gamut:E27); 'Marking' states
%   the marking the result carries, which dst then carries, whatever the
%   two files did.
%
%   With several sources (a cell array or a string array), the result is
%   that of appending them one by one, in order, made at once: dst is
%   copied once and gets every file's rows or none.  An error names the
%   file it is about.
%
%   Opening a marked file issues the warning gamut:marking, once per file;
%   warning('off', 'gamut:marking') turns it off.
p = inputParser;
p.addParameter('Marking', []);
p.parse(varargin{:});
given = ~(isnumeric(p.Results.Marking) && isempty(p.Results.Marking));   % '' is refused
if iscell(src) || (isstring(src) && ~isscalar(src))
    args = {char(dst), cellstr(src)};
    cmd = 'append_files';
else
    args = {char(dst), char(src)};
    cmd = 'append';
end
if given
    args{end + 1} = char(p.Results.Marking);
end
n = gamut_mex(cmd, args{:});
end
