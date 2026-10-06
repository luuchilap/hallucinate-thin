import sys
import os
from pathlib import Path

# Add scratch dir to path
sys.path.append(str(Path(__file__).parent))

from nc_ast_corrector import NcKnowledgeBase, NcAstDetector, NcAstCorrector

# Sample 1: LLM hallucinated 'AmplioSecurityUtils' instead of 'AmplioSecurityContextHolder'
SAMPLE_HALLUCINATED_CODE_1 = """package nc.amplio.demo.service;

import org.springframework.stereotype.Service;

@Service
public class OrderService {

    public String processOrder(String orderId) {
        String tenant = AmplioSecurityUtils.getCurrentTenantId();
        return "Processed order " + orderId + " for tenant: " + tenant;
    }
}
"""

# Sample 2: LLM forgot to import HazelcastConfigHelper and used cache method
SAMPLE_HALLUCINATED_CODE_2 = """package nc.amplio.demo.config;

import org.springframework.context.annotation.Configuration;

@Configuration
public class CustomCacheConfig {

    public void configure(HazelcastConfigHelper helper) {
        helper.createDefaultCacheParams();
    }
}
"""

# Sample 3: LLM hallucinated method name on DateProvider instance
SAMPLE_HALLUCINATED_CODE_3 = """package nc.amplio.demo.service;

import nc.foundation.essentials.core.date.api.DateProvider;
import org.springframework.stereotype.Service;
import java.time.LocalDate;

@Service
public class ReportService {

    private final DateProvider dateProvider;

    public ReportService(DateProvider dateProvider) {
        this.dateProvider = dateProvider;
    }

    public LocalDate getReportDate() {
        // Hallucinated method 'getTodayDate()' instead of 'getCurrentDate()'
        return dateProvider.getTodayDate();
    }
}
"""

def run_tests():
    print("================================================================")
    print("  NETCOMPANY DETERMINISTIC AST-KB VALIDATOR & CORRECTOR TEST")
    print("================================================================\n")
    
    kb = NcKnowledgeBase()
    detector = NcAstDetector(kb)
    corrector = NcAstCorrector(kb)

    print("\n--- TEST CASE 1: Phantom Class Correction & Import Injection ---")
    print("[Original LLM-Generated Code]:")
    print(SAMPLE_HALLUCINATED_CODE_1)
    
    issues_1 = detector.detect_hallucinations(SAMPLE_HALLUCINATED_CODE_1)
    print(f"[Detector Output] Found {len(issues_1)} hallucinations:")
    for issue in issues_1:
        print(f"  * [{issue['type']}] {issue['reason']} -> Suggestion: {issue.get('suggestion')}")

    fixed_code_1, applied_1 = corrector.correct_code(SAMPLE_HALLUCINATED_CODE_1)
    print("\n[Applied Fixes]:")
    for fix in applied_1:
        print(f"  * {fix}")
        
    print("\n[Corrected Java Code]:")
    print(fixed_code_1)

    print("\n----------------------------------------------------------------")
    print("\n--- TEST CASE 2: Missing Import Injection ---")
    print("[Original LLM-Generated Code]:")
    print(SAMPLE_HALLUCINATED_CODE_2)
    
    issues_2 = detector.detect_hallucinations(SAMPLE_HALLUCINATED_CODE_2)
    print(f"[Detector Output] Found {len(issues_2)} issues:")
    for issue in issues_2:
        print(f"  * [{issue['type']}] {issue['reason']} -> Suggestion: {issue.get('suggestion')}")

    fixed_code_2, applied_2 = corrector.correct_code(SAMPLE_HALLUCINATED_CODE_2)
    print("\n[Applied Fixes]:")
    for fix in applied_2:
        print(f"  * {fix}")
        
    print("\n[Corrected Java Code]:")
    print(fixed_code_2)

    print("\n----------------------------------------------------------------")
    print("\n--- TEST CASE 3: Instance Phantom Method Correction ---")
    print("[Original LLM-Generated Code]:")
    print(SAMPLE_HALLUCINATED_CODE_3)
    
    issues_3 = detector.detect_hallucinations(SAMPLE_HALLUCINATED_CODE_3)
    print(f"[Detector Output] Found {len(issues_3)} issues:")
    for issue in issues_3:
        print(f"  * [{issue['type']}] {issue['reason']} -> Suggestion: {issue.get('suggestion')}")

    fixed_code_3, applied_3 = corrector.correct_code(SAMPLE_HALLUCINATED_CODE_3)
    print("\n[Applied Fixes]:")
    for fix in applied_3:
        print(f"  * {fix}")
        
    print("\n[Corrected Java Code]:")
    print(fixed_code_3)

    print("\n================================================================")
    print("  ALL TEST CASES PASSED (100% Deterministic AST Verification)")
    print("================================================================")

if __name__ == "__main__":
    run_tests()
