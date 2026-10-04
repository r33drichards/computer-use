// terraform-provider-computeruse manages computeruse sessions and their policies
// from Terraform or OpenTofu.
package main

import (
	"context"
	"flag"
	"log"

	"github.com/hashicorp/terraform-plugin-framework/providerserver"

	"github.com/r33drichards/computer-use/terraform-provider-computeruse/internal/provider"
)

// version is set by the release build (-ldflags "-X main.version=...").
var version = "dev"

func main() {
	var debug bool
	flag.BoolVar(&debug, "debug", false, "run with support for debuggers such as delve")
	flag.Parse()

	err := providerserver.Serve(context.Background(), provider.New(version), providerserver.ServeOpts{
		Address: "registry.terraform.io/r33drichards/computeruse",
		Debug:   debug,
	})
	if err != nil {
		log.Fatal(err)
	}
}
