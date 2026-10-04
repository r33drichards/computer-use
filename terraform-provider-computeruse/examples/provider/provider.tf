terraform {
  required_providers {
    computeruse = { source = "r33drichards/computeruse" }
  }
}

# The token is best left out of the configuration: set COMPUTERUSE_TOKEN.
provider "computeruse" {
  endpoint = "https://api.computeruse.site" # the default; or COMPUTERUSE_ENDPOINT
}
