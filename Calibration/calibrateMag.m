function [center, scale, Mcal] = calibrateMag(filename)
% calibrateMag  Load raw magnetometer CSV and compute hard/soft-iron calibration.
%
%  [center, scale, Mcal] = calibrateMag(filename)
%
%  INPUT
%    filename : path to CSV with header row: timestamp_ms,mx,my,mz
%               Values must be raw MMC5983MA counts (uint32, ~0–262143).
%               Rows where all three axes are zero are treated as invalid
%               (sensor not ready / firmware disabled) and are discarded.
%
%  OUTPUTS
%    center : 1×3  hard-iron offset  [X Y Z]  (raw counts)
%    scale  : 1×3  soft-iron scale   [X Y Z]  (counts per unit sphere radius)
%    Mcal   : N×3  calibrated magnetometer readings (unit-sphere normalised)
%
%  FIRMWARE USAGE
%  --------------
%  The calibration is applied in VertiSea.ino as:
%    mx = (raw_x - offset[0]) * scale[0]
%    my = (raw_y - offset[1]) * scale[1]
%    mz = (raw_z - offset[2]) * scale[2]
%
%  This function prints the values in the exact C struct format ready to
%  paste into the MagCal block in VertiSea.ino.
%
%  ALGORITHM
%  ---------
%  1. Fit an ellipsoid to the raw (Mx, My, Mz) point cloud using a
%     least-squares SVD approach (Algebraic distance minimisation).
%  2. Extract the ellipsoid centre → hard-iron offset.
%  3. Compute per-axis scale factors so that the calibrated data lies on
%     a sphere of radius 1.  Scale[i] = 1 / semi-axis[i].
%
%  REQUIREMENTS
%  ------------
%  Collect data by slowly rotating the buoy through all orientations
%  (full-sphere sweep) while logging.  At least 200 valid samples are
%  needed; 500+ is recommended for a good ellipsoid fit.
%
%  See also: docs/calibration.md

  % -------------------------------------------------------------------------
  %  1. Load data
  % -------------------------------------------------------------------------
  T = readtable(filename);

  Mx = T.mx;
  My = T.my;
  Mz = T.mz;

  % -------------------------------------------------------------------------
  %  2. Remove invalid (all-zero) rows
  %     The firmware writes (0,0,0) when the magnetometer is disabled or
  %     when getMeasurementXYZ() returns false.  These rows must be removed
  %     before fitting or the ellipsoid will be pulled toward the origin.
  % -------------------------------------------------------------------------
  valid = ~(Mx == 0 & My == 0 & Mz == 0);
  Mx = Mx(valid);
  My = My(valid);
  Mz = Mz(valid);

  nValid = numel(Mx);
  fprintf('Total rows: %d   Valid (non-zero): %d   Discarded: %d\n', ...
          height(T), nValid, height(T) - nValid);

  if nValid < 50
    error('calibrateMag:insufficientData', ...
          'Only %d valid samples after removing zeros. Need at least 50 for a reliable fit.', nValid);
  end

  % -------------------------------------------------------------------------
  %  3. Ellipsoid fit via SVD (algebraic least-squares)
  %
  %  The general quadric surface  x'Ax + b'x + J = 0  is constrained to an
  %  ellipsoid by the design matrix below.  The last singular vector of the
  %  augmented design matrix gives the coefficient vector v.
  %
  %  Design matrix columns:
  %    [Mx^2, My^2, Mz^2, 2*Mx*My, 2*Mx*Mz, 2*My*Mz, 2*Mx, 2*My, 2*Mz, 1]
  % -------------------------------------------------------------------------
  D = [ Mx.^2,  My.^2,  Mz.^2, ...
        2*Mx.*My, 2*Mx.*Mz, 2*My.*Mz, ...
        2*Mx,    2*My,    2*Mz,    ones(nValid,1) ];

  [~, ~, V] = svd(D, 'econ');
  v = V(:, end);   % eigenvector corresponding to smallest singular value

  % -------------------------------------------------------------------------
  %  4. Unpack ellipsoid parameters
  %
  %  The symmetric matrix A and linear term b are:
  %    A = [ v(1)  v(4)  v(5) ]
  %        [ v(4)  v(2)  v(6) ]
  %        [ v(5)  v(6)  v(3) ]
  %    b = [ v(7); v(8); v(9) ]
  %    J =   v(10)
  % -------------------------------------------------------------------------
  A = [ v(1), v(4), v(5);
        v(4), v(2), v(6);
        v(5), v(6), v(3) ];
  b = v(7:9);
  J = v(10);

  % Verify A is positive-definite (required for a valid ellipsoid).
  % If eigenvalues are not all positive, the fit is degenerate.
  eigA = eig(A);
  if any(eigA <= 0)
    warning('calibrateMag:degenerateFit', ...
            'Ellipsoid matrix A is not positive-definite. The fit may be degenerate.\n%s', ...
            'Ensure the data covers all orientations (full-sphere sweep).');
  end

  % -------------------------------------------------------------------------
  %  5. Hard-iron offset (ellipsoid centre)
  %
  %  The centre of the ellipsoid x'Ax + b'x + J = 0 is:
  %    center = -A^{-1} * b / 2
  %  (factor of 2 because the linear term in the standard form is 2*b'*x)
  % -------------------------------------------------------------------------
  center = -(A \ b) / 2;   % 3×1 column vector

  % -------------------------------------------------------------------------
  %  6. Soft-iron scale factors
  %
  %  After subtracting the centre, the ellipsoid becomes:
  %    (x - c)' * A * (x - c) = c_val
  %  where  c_val = b' * A^{-1} * b / 4 - J
  %
  %  The semi-axes of the ellipsoid are  a_i = sqrt(c_val / lambda_i)
  %  where lambda_i are the eigenvalues of A.
  %
  %  For the firmware's per-axis (diagonal) model we use the diagonal
  %  elements of A as an approximation of the principal axes aligned with
  %  the sensor axes.  The scale factor for axis i is:
  %    scale[i] = 1 / semi_axis[i] = sqrt(A_ii / c_val)
  %
  %  This normalises each axis so that the calibrated data lies on a
  %  unit sphere (mean radius ≈ 1).
  % -------------------------------------------------------------------------
  c_val = (b' * (A \ b)) / 4 - J;

  if c_val <= 0
    error('calibrateMag:degenerateFit', ...
          'c_val = %.6g <= 0. The ellipsoid fit is degenerate. Check your data.', c_val);
  end

  semi_axes = sqrt(c_val ./ diag(A));   % 3×1, semi-axis lengths per sensor axis

  if any(~isreal(semi_axes)) || any(semi_axes <= 0)
    error('calibrateMag:degenerateFit', ...
          'One or more semi-axes are non-positive or complex. Check data coverage.');
  end

  % Scale factor = 1 / semi_axis  (maps ellipsoid to unit sphere per axis)
  scale = (1 ./ semi_axes)';   % 1×3 row vector

  % -------------------------------------------------------------------------
  %  7. Apply calibration
  %
  %  Firmware formula:  cal = (raw - center) * scale   (element-wise)
  % -------------------------------------------------------------------------
  M    = [Mx, My, Mz];
  Mcal = (M - center') .* scale;   % broadcast: center' is 1×3

  % -------------------------------------------------------------------------
  %  8. Quality statistics
  % -------------------------------------------------------------------------
  r_raw = sqrt(sum(M.^2,    2));
  r_cal = sqrt(sum(Mcal.^2, 2));

  fprintf('\n--- Calibration Results ---\n');
  fprintf('Hard-iron offsets (center): [%.4f, %.4f, %.4f]\n', center(1), center(2), center(3));
  fprintf('Soft-iron scales:           [%.6f, %.6f, %.6f]\n', scale(1),  scale(2),  scale(3));
  fprintf('\nRaw data:  mean radius = %.3f,  std = %.3f\n', mean(r_raw), std(r_raw));
  fprintf('Cal data:  mean radius = %.4f,  std = %.4f\n',  mean(r_cal), std(r_cal));
  fprintf('           (ideal: mean=1.0000, std→0)\n');

  % -------------------------------------------------------------------------
  %  9. Print firmware-ready C struct for copy-paste into VertiSea.ino
  % -------------------------------------------------------------------------
  fprintf('\n--- Paste into VertiSea.ino (MagCal block) ---\n');
  fprintf('} magCal = {\n');
  fprintf('  { %.4ff, %.4ff, %.4ff},  // hard-iron offsets\n', ...
          center(1), center(2), center(3));
  fprintf('  { %.6ff, %.6ff, %.6ff}   // soft-iron scales\n', ...
          scale(1), scale(2), scale(3));
  fprintf('};\n');

  % -------------------------------------------------------------------------
  %  10. Plots
  % -------------------------------------------------------------------------

  % 3-D scatter: raw vs calibrated
  figure('Name', 'Magnetometer Calibration — 3D Scatter');
  subplot(1,2,1);
  scatter3(Mx, My, Mz, 6, '.', 'MarkerEdgeColor', [0.2 0.4 0.8]);
  axis equal; grid on;
  title('Raw magnetometer (counts)');
  xlabel('X'); ylabel('Y'); zlabel('Z');

  subplot(1,2,2);
  scatter3(Mcal(:,1), Mcal(:,2), Mcal(:,3), 6, '.', 'MarkerEdgeColor', [0.8 0.3 0.1]);
  axis equal; grid on;
  title('Calibrated magnetometer (unit sphere)');
  xlabel('X'); ylabel('Y'); zlabel('Z');

  % Radius histograms
  figure('Name', 'Magnetometer Calibration — Radius Distribution');
  subplot(1,2,1);
  histogram(r_raw, 50, 'FaceColor', [0.2 0.4 0.8]);
  title('Raw Radii');
  xlabel('||v||  (counts)');
  ylabel('Count');

  subplot(1,2,2);
  histogram(r_cal, 50, 'FaceColor', [0.8 0.3 0.1]);
  xline(1.0, 'k--', 'LineWidth', 1.5);
  title('Calibrated Radii');
  xlabel('||v||  (normalised)');
  ylabel('Count');

end
