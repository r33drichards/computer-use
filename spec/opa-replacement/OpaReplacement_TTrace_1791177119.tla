---- MODULE OpaReplacement_TTrace_1791177119 ----
EXTENDS OpaReplacement_TEConstants, Sequences, TLCExt, Toolbox, Naturals, TLC, OpaReplacement

_expression ==
    LET OpaReplacement_TEExpression == INSTANCE OpaReplacement_TEExpression
    IN OpaReplacement_TEExpression!expression
----

_trace ==
    LET OpaReplacement_TETrace == INSTANCE OpaReplacement_TETrace
    IN OpaReplacement_TETrace!trace
----

_inv ==
    ~(
        TLCGet("level") = Len(_TETrace)
        /\
        call = ("denied")
        /\
        phase = ((p1 :> "stopping" @@ p2 :> "serving" @@ p3 :> "none" @@ p4 :> "starting"))
        /\
        tries = (0)
        /\
        conn = (None)
        /\
        deletes = (1)
        /\
        endpoint = ((p1 :> TRUE @@ p2 :> TRUE @@ p3 :> FALSE @@ p4 :> FALSE))
        /\
        reachable = ((p1 :> TRUE @@ p2 :> TRUE @@ p3 :> FALSE @@ p4 :> FALSE))
    )
----

_init ==
    /\ tries = _TETrace[1].tries
    /\ conn = _TETrace[1].conn
    /\ deletes = _TETrace[1].deletes
    /\ reachable = _TETrace[1].reachable
    /\ call = _TETrace[1].call
    /\ phase = _TETrace[1].phase
    /\ endpoint = _TETrace[1].endpoint
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ tries  = _TETrace[i].tries
        /\ tries' = _TETrace[j].tries
        /\ conn  = _TETrace[i].conn
        /\ conn' = _TETrace[j].conn
        /\ deletes  = _TETrace[i].deletes
        /\ deletes' = _TETrace[j].deletes
        /\ reachable  = _TETrace[i].reachable
        /\ reachable' = _TETrace[j].reachable
        /\ call  = _TETrace[i].call
        /\ call' = _TETrace[j].call
        /\ phase  = _TETrace[i].phase
        /\ phase' = _TETrace[j].phase
        /\ endpoint  = _TETrace[i].endpoint
        /\ endpoint' = _TETrace[j].endpoint

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("OpaReplacement_TTrace_1791177119.json", _TETrace)

=============================================================================

 Note that you can extract this module `OpaReplacement_TEExpression`
  to a dedicated file to reuse `expression` (the module in the 
  dedicated `OpaReplacement_TEExpression.tla` file takes precedence 
  over the module `OpaReplacement_TEExpression` below).

---- MODULE OpaReplacement_TEExpression ----
EXTENDS OpaReplacement_TEConstants, Sequences, TLCExt, Toolbox, Naturals, TLC, OpaReplacement

expression == 
    [
        \* To hide variables of the `OpaReplacement` spec from the error trace,
        \* remove the variables below.  The trace will be written in the order
        \* of the fields of this record.
        tries |-> tries
        ,conn |-> conn
        ,deletes |-> deletes
        ,reachable |-> reachable
        ,call |-> call
        ,phase |-> phase
        ,endpoint |-> endpoint
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_triesUnchanged |-> tries = tries'
        
        \* Format the `tries` variable as Json value.
        \* ,_triesJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(tries)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_triesModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].tries # _TETrace[s-1].tries
        \*             THEN 1 + F[s-1] ELSE F[s-1]
        \*     IN F[_TEPosition - 1]
    ]

=============================================================================



Parsing and semantic processing can take forever if the trace below is long.
 In this case, it is advised to uncomment the module below to deserialize the
 trace from a generated binary file.

\*
\*---- MODULE OpaReplacement_TETrace ----
\*EXTENDS OpaReplacement_TEConstants, IOUtils, TLC, OpaReplacement
\*
\*trace == IODeserialize("OpaReplacement_TTrace_1791177119.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE OpaReplacement_TETrace ----
EXTENDS OpaReplacement_TEConstants, TLC, OpaReplacement

trace == 
    <<
    ([call |-> "idle",phase |-> (p1 :> "serving" @@ p2 :> "serving" @@ p3 :> "none" @@ p4 :> "none"),tries |-> 0,conn |-> None,deletes |-> 0,endpoint |-> (p1 :> TRUE @@ p2 :> TRUE @@ p3 :> FALSE @@ p4 :> FALSE),reachable |-> (p1 :> TRUE @@ p2 :> TRUE @@ p3 :> FALSE @@ p4 :> FALSE)]),
    ([call |-> "idle",phase |-> (p1 :> "draining" @@ p2 :> "serving" @@ p3 :> "none" @@ p4 :> "starting"),tries |-> 0,conn |-> None,deletes |-> 1,endpoint |-> (p1 :> TRUE @@ p2 :> TRUE @@ p3 :> FALSE @@ p4 :> FALSE),reachable |-> (p1 :> TRUE @@ p2 :> TRUE @@ p3 :> FALSE @@ p4 :> FALSE)]),
    ([call |-> "idle",phase |-> (p1 :> "stopping" @@ p2 :> "serving" @@ p3 :> "none" @@ p4 :> "starting"),tries |-> 0,conn |-> None,deletes |-> 1,endpoint |-> (p1 :> TRUE @@ p2 :> TRUE @@ p3 :> FALSE @@ p4 :> FALSE),reachable |-> (p1 :> TRUE @@ p2 :> TRUE @@ p3 :> FALSE @@ p4 :> FALSE)]),
    ([call |-> "denied",phase |-> (p1 :> "stopping" @@ p2 :> "serving" @@ p3 :> "none" @@ p4 :> "starting"),tries |-> 0,conn |-> None,deletes |-> 1,endpoint |-> (p1 :> TRUE @@ p2 :> TRUE @@ p3 :> FALSE @@ p4 :> FALSE),reachable |-> (p1 :> TRUE @@ p2 :> TRUE @@ p3 :> FALSE @@ p4 :> FALSE)])
    >>
----


=============================================================================

---- MODULE OpaReplacement_TEConstants ----
EXTENDS OpaReplacement

CONSTANTS p1, p2, p3, p4

=============================================================================

---- CONFIG OpaReplacement_TTrace_1791177119 ----
CONSTANTS
    Pods = { p1 , p2 , p3 , p4 }
    Initial = { p1 , p2 }
    None = None
    MaxDeletes = 2
    DrainWaitsForEndpoints = FALSE
    ReadyWaitsForNetwork = FALSE
    Retries = 0
    p4 = p4
    p3 = p3
    p2 = p2
    None = None
    p1 = p1

INVARIANT
    _inv

CHECK_DEADLOCK
    \* CHECK_DEADLOCK off because of PROPERTY or INVARIANT above.
    FALSE

INIT
    _init

NEXT
    _next

CONSTANT
    _TETrace <- _trace

ALIAS
    _expression
=============================================================================
\* Generated on Mon Oct 05 05:12:00 UTC 2026