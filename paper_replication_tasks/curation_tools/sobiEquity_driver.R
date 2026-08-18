#!/usr/bin/env Rscript
# Curator-only driver: loads sobiEquity's archived data, prepares the travel-time
# table exactly as README.Rmd's join chunks do, and calls the pinned b2sfca()/
# c2sfca() functions verbatim. Reads one JSON case from stdin, writes one JSON
# result to stdout. Never modifies the official package source.

suppressPackageStartupMessages({
  library(sobiEquity)
  library(dplyr)
  library(sf)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1) stop("usage: sobiEquity_driver.R <input.json>")
case <- fromJSON(args[[1]], simplifyVector = TRUE)

required <- c("method", "threshold", "hub_filter")
missing <- setdiff(required, names(case))
if (length(missing) > 0) stop(paste("missing required fields:", paste(missing, collapse = ", ")))
if (!case$method %in% c("b2sfca", "c2sfca")) stop("method must be b2sfca or c2sfca")
if (!is.numeric(case$threshold) || length(case$threshold) != 1 || case$threshold <= 0) {
  stop("threshold must be a single positive number")
}
if (!case$hub_filter %in% c("conventional_active", "all_active")) {
  stop("hub_filter must be conventional_active or all_active")
}

data("ttm_walk", package = "sobiEquity")
data("sobi_hubs", package = "sobiEquity")
data("population_50x50", package = "sobiEquity")

ttm <- left_join(ttm_walk, population_50x50 %>% st_drop_geometry(), by = "UID")
ttm <- ttm %>%
  left_join(sobi_hubs %>% st_drop_geometry() %>% dplyr::select(OBJECTID, RACKS_AMOU), by = "OBJECTID")
names(ttm) <- c("UID", "hub", "travel_time", "hub_type", "hub_status", "population", "racks")

ttm <- if (case$hub_filter == "conventional_active") {
  ttm %>% dplyr::filter(hub_type == "Conventional" & hub_status == "Active")
} else {
  ttm %>% dplyr::filter(hub_status == "Active")
}

result <- if (case$method == "b2sfca") {
  b2sfca(ttm = ttm, threshold = case$threshold)
} else {
  c2sfca(ttm = ttm, threshold = case$threshold)
}

output <- list(
  method = case$method,
  threshold = case$threshold,
  hub_filter = case$hub_filter,
  los = result$los %>% arrange(hub) %>% as.data.frame(),
  accessibility = result$accessibility %>% arrange(UID) %>% as.data.frame()
)

cat(toJSON(output, dataframe = "columns", digits = 17, na = "null", auto_unbox = TRUE))
