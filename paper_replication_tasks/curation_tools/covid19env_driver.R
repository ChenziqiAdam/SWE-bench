#!/usr/bin/env Rscript
# Curator-only driver: loads covid19env's archived data, reproduces README.Rmd's
# data-preparation and spatial-weights chunks exactly (islands excluded, per the
# "minus-islands" chunks actually used by the paper's models), and calls the
# pinned spsur::spsurtime() verbatim. Reads one JSON case from stdin, writes one
# JSON result to stdout. Never modifies the official package source.

suppressPackageStartupMessages({
  library(covid19env)
  library(dplyr)
  library(sf)
  library(spdep)
  library(spatialreg)
  library(spsur)
  library(plm)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1) stop("usage: covid19env_driver.R <input.json>")
case <- fromJSON(args[[1]], simplifyVector = TRUE)

required <- c("lag_spec", "restricted")
missing <- setdiff(required, names(case))
if (length(missing) > 0) stop(paste("missing required fields:", paste(missing, collapse = ", ")))
if (!case$lag_spec %in% c("lag8", "lag11", "lag11w")) stop("lag_spec must be lag8, lag11, or lag11w")
if (!is.logical(case$restricted) || length(case$restricted) != 1) stop("restricted must be a single boolean")

data("covid19_spain_1", package = "covid19env")
data("provinces_spain", package = "covid19env")

provinces_spain <- provinces_spain %>%
  mutate(GDPpc = GDPpc / 1000)

covid19_spain <- covid19_spain_1 %>%
  left_join(provinces_spain %>% st_drop_geometry(),
            by = c("province", "CCAA", "ID_INE"))

GPanel <- plm::pdata.frame(covid19_spain %>%
                             filter(province != "Baleares", CCAA != "Canarias") %>%
                             select(province,
                                    Date,
                                    Incidence,
                                    Median_Age,
                                    Male2Female,
                                    Older,
                                    GDPpc,
                                    Density,
                                    Transit,
                                    Mean_Temp_lag8,
                                    Humidity_lag8,
                                    Sunshine_Hours_lag8,
                                    Mean_Temp_lag11,
                                    Humidity_lag11,
                                    Sunshine_Hours_lag11,
                                    Mean_Temp_lag11w,
                                    Humidity_lag11w,
                                    Sunshine_Hours_lag11w),
                           c("province", "Date"))

Wmat <- provinces_spain %>%
  filter(province != "Baleares", CCAA != "Canarias") %>%
  as("Spatial") %>%
  poly2nb(queen = TRUE) %>%
  nb2mat(zero.policy = TRUE)

listw <- mat2listw(Wmat, style = "W")

formula_lag8 <- log(Incidence) ~
  log(GDPpc) + log(Older) + log(Density) + Transit +
  log(Humidity_lag8) + log(Mean_Temp_lag8) + log(Sunshine_Hours_lag8 + 0.1)

formula_lag11 <- log(Incidence) ~
  log(GDPpc) + log(Older) + log(Density) + Transit +
  log(Humidity_lag11) + log(Mean_Temp_lag11) + log(Sunshine_Hours_lag11 + 0.1)

formula_lag11w <- log(Incidence) ~
  log(GDPpc) + log(Older) + log(Density) + Transit +
  log(Humidity_lag11w) + log(Mean_Temp_lag11w) + log(Sunshine_Hours_lag11w + 0.1)

formula <- switch(case$lag_spec,
  lag8 = formula_lag8,
  lag11 = formula_lag11,
  lag11w = formula_lag11w
)

fit_args <- list(
  formula = formula,
  data = GPanel,
  time = GPanel$Date,
  type = "slm",
  fit_method = "3sls",
  listw = listw
)

if (isTRUE(case$restricted)) {
  T_periods <- max(covid19_spain$Date) - min(covid19_spain$Date) + 1
  k <- 8
  coef_rest <- 2
  R2 <- matrix(0, nrow = (T_periods - 1) * coef_rest, ncol = k * T_periods)
  for (i in 1:(T_periods - 1)) {
    R2[i, 2] <- 1
    R2[i, (2 + i * k)] <- -1
    R2[(i + T_periods - 1), 3] <- 1
    R2[(i + T_periods - 1), (3 + i * k)] <- -1
  }
  b2 <- matrix(0, ncol = (T_periods - 1) * coef_rest)
  fit_args$R <- R2
  fit_args$b <- b2
}

# spsur3sls.R's fitting routine unconditionally cat()s a timing line with no
# suppression flag; swallow it so stdout carries only the final JSON payload.
invisible(capture.output(fit <- do.call(spsur::spsurtime, fit_args)))

coefficients <- as.numeric(fit$coefficients)
coef_names <- names(fit$coefficients)
std_errors <- as.numeric(fit$rest.se)
rho <- as.numeric(fit$deltas)
r2_by_equation <- as.numeric(fit$R2[-1])
pooled_r2 <- as.numeric(fit$R2[1])

output <- list(
  lag_spec = case$lag_spec,
  restricted = case$restricted,
  coefficient_names = coef_names,
  coefficients = coefficients,
  std_errors = std_errors,
  rho = rho,
  r2_by_equation = r2_by_equation,
  pooled_r2 = pooled_r2
)

cat(toJSON(output, dataframe = "columns", digits = 17, na = "null", auto_unbox = TRUE))
