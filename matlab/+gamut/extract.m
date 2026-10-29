function extract(src, dst, rows)
%EXTRACT Writes the selected rows of src as a new file dst.
%   gamut.extract(src, dst, rows)     % rows: 1-based positions, ':' every row
%   Row ids are kept, every table whole, and a changing mesh keeps only the
%   instances its rows use. [] extracts no rows, as select may return.
if nargin < 3, rows = ':'; end
if (ischar(rows) || isstring(rows)) && isscalar(string(rows)) && string(rows) == ":"
    gamut_mex('extract', char(src), char(dst), ':');
    return
end
if islogical(rows) || ~isnumeric(rows) || any(rows(:) ~= fix(rows(:)))
    error('gamut:usage', 'rows are whole-number positions (for a mask, use find)');
end
gamut_mex('extract', char(src), char(dst), double(rows(:)) - 1);
end
