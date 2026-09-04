import sys
from app.engine import AssuranceEngine
from simulator.scenarios import all_scenarios, GROUND_TRUTH

def run():
    engine = AssuranceEngine()
    scenarios = all_scenarios()
    
    passed = 0
    total = len(scenarios)
    
    print(f"{'Scenario Name':<35} | {'Expected Violation':<35} | {'Actual Violation':<35} | {'Result'}")
    print("-" * 120)
    
    for name, stream in scenarios.items():
        truth = GROUND_TRUTH.get(name)
        if not truth:
            print(f"ERROR: {name} not found in GROUND_TRUTH")
            continue
            
        cases = engine.investigate(stream)
        
        expected_type = truth["violation_type"]
        actual_types = [case.violation_type.value for case in cases]
        
        # If no violation expected
        if not truth["expects_violation"]:
            if not cases:
                result = "PASS"
                passed += 1
                actual_str = "None"
            else:
                result = "FAIL"
                actual_str = ", ".join(actual_types)
        else:
            # Expected a violation
            if expected_type in actual_types:
                result = "PASS"
                passed += 1
                actual_str = expected_type
            else:
                result = "FAIL"
                actual_str = ", ".join(actual_types) if actual_types else "None"
                
        expected_str = expected_type if expected_type else "None"
        print(f"{name:<35} | {expected_str:<35} | {actual_str:<35} | {result}")
        
    print("-" * 120)
    print(f"Total: {passed}/{total} passed ({(passed/total)*100:.0f}%)")
    
    if passed != total:
        sys.exit(1)

if __name__ == "__main__":
    run()
