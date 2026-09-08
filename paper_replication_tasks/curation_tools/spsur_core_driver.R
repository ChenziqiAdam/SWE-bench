#!/usr/bin/env Rscript
# Curator-only direct numeric adapter for spsur 1.0.1.3.
suppressPackageStartupMessages(library(jsonlite))
suppressPackageStartupMessages(library(spsur))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1) stop("usage: spsur_core_driver.R input.json")
v <- fromJSON(args[[1]], simplifyVector = FALSE)
G <- length(v$y); N <- length(v$y[[1]]); P <- length(v$x[[1]][[1]])
Ypanel <- matrix(as.numeric(unlist(v$y)), nrow = N, ncol = G)
Y <- as.vector(Ypanel)
W <- matrix(as.numeric(unlist(v$w)), nrow = N, ncol = N, byrow = TRUE)
X <- matrix(0, nrow = G * N, ncol = G * P)
for (g in seq_len(G)) {
  block <- matrix(as.numeric(unlist(v$x[[g]])), nrow = N, ncol = P, byrow = TRUE)
  X[((g - 1) * N + 1):(g * N), ((g - 1) * P + 1):(g * P)] <- block
}
colnames(X) <- unlist(lapply(seq_len(G), function(g) paste0("x_", g, "_", seq_len(P))))

shared <- as.integer(unlist(v$shared_beta_columns)) + 1L
R <- NULL; b <- NULL
if (length(shared)) {
  R <- matrix(0, nrow = length(shared) * (G - 1), ncol = G * P)
  row <- 1L
  for (j in shared) for (g in 2:G) {
    R[row, j] <- 1
    R[row, (g - 1) * P + j] <- -1
    row <- row + 1L
  }
  b <- matrix(0, nrow = nrow(R), ncol = 1)
}

fit <- spsur3sls(X = X, Y = Y, listw = W, G = G, N = N, Tm = 1,
                 p = rep(P, G), type = "slm", maxlagW = 2, R = R, b = b)
compact <- as.numeric(fit$coefficients); names(compact) <- names(fit$coefficients)
compact.se <- as.numeric(fit$rest.se); names(compact.se) <- names(fit$rest.se)
beta <- matrix(NA_real_, G, P); beta.se <- matrix(NA_real_, G, P)
for (g in seq_len(G)) for (j in seq_len(P)) {
  key <- if (j %in% shared) paste0("x_1_", j) else paste0("x_", g, "_", j)
  beta[g, j] <- compact[[key]]; beta.se[g, j] <- compact.se[[key]]
}
rho <- as.numeric(fit$deltas); rho.se <- as.numeric(fit$deltas.se)
direct <- matrix(NA_real_, G, P - 1); total <- matrix(NA_real_, G, P - 1)
for (g in seq_len(G)) {
  multiplier <- solve(diag(N) - rho[g] * W)
  direct[g, ] <- beta[g, -1] * sum(diag(multiplier)) / N
  total[g, ] <- beta[g, -1] * sum(multiplier) / N
}
result <- list(
  beta = unname(split(beta, row(beta))),
  beta_standard_errors = unname(split(beta.se, row(beta.se))),
  rho = rho,
  rho_standard_errors = rho.se,
  r2_by_equation = as.numeric(fit$R2[-1]), pooled_r2 = as.numeric(fit$R2[1]),
  direct_effects = unname(split(direct, row(direct))),
  indirect_effects = unname(split(total - direct, row(direct))),
  total_effects = unname(split(total, row(total)))
)
cat(toJSON(result, auto_unbox = TRUE, digits = 17, null = "null"))
